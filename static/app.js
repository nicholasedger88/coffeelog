const debounce = (fn, wait = 250) => {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), wait);
  };
};

const showLoading = (message) => {
  const modal = document.getElementById("loading-modal");
  const text = document.getElementById("loading-message");
  if (!modal || !text) return;
  text.textContent = message;
  modal.classList.add("active");
  modal.setAttribute("aria-hidden", "false");
  document.body.setAttribute("aria-busy", "true");
};

const hideLoading = () => {
  const modal = document.getElementById("loading-modal");
  if (!modal) return;
  modal.classList.remove("active");
  modal.setAttribute("aria-hidden", "true");
  document.body.removeAttribute("aria-busy");
};

const setupAutocomplete = () => {
  document.querySelectorAll(".autocomplete").forEach((wrapper) => {
    const input = wrapper.querySelector("input");
    const dropdown = wrapper.querySelector(".suggestions");
    const field = wrapper.dataset.field;

    const hide = () => {
      dropdown.style.display = "none";
      dropdown.innerHTML = "";
    };

    const fetchSuggestions = debounce(async () => {
      const term = input.value.trim();
      if (!term) {
        hide();
        return;
      }
      const response = await fetch(`/api/suggest?field=${field}&term=${encodeURIComponent(term)}`);
      const suggestions = await response.json();
      dropdown.innerHTML = "";
      if (suggestions.length === 0) {
        hide();
        return;
      }
      suggestions.forEach((suggestion) => {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = suggestion;
        button.addEventListener("click", () => {
          input.value = suggestion;
          hide();
        });
        dropdown.appendChild(button);
      });
      dropdown.style.display = "block";
    }, 250);

    input.addEventListener("input", fetchSuggestions);
    input.addEventListener("blur", () => setTimeout(hide, 150));
  });
};

const setupGrindSettings = () => {
  const grinder = document.getElementById("grinder-select");
  const grindSetting = document.getElementById("grind-setting-select");
  if (!grinder || !grindSetting || !window.coffeeLogConfig) {
    return;
  }

  const updateOptions = () => {
    const value = grinder.value;
    let options = [];
    if (value === "Aergrind (Nicholas)") {
      options = window.coffeeLogConfig.aergrindSettings;
    }
    if (value === "Belinda’s grinder") {
      options = window.coffeeLogConfig.belindaSettings;
    }
    grindSetting.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = options.length ? "Select" : "Select grinder first";
    grindSetting.appendChild(placeholder);
    options.forEach((optionValue) => {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = optionValue;
      grindSetting.appendChild(option);
    });
  };

  grinder.addEventListener("change", updateOptions);
};

const setupAddMap = () => {
  const mapEl = document.getElementById("map");
  if (!mapEl) return;

  const map = L.map(mapEl).setView([10, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
  }).addTo(map);

  const marker = L.marker([10, 0], { draggable: false }).addTo(map);
  const latInput = document.getElementById("latitude");
  const lonInput = document.getElementById("longitude");
  const altitudeInput = document.getElementById("altitude");
  const countryInput = document.getElementById("country");
  const locationInput = document.getElementById("location");

  let userTouchedCountry = false;
  let userTouchedLocation = false;
  let userTouchedAltitude = false;
  let clickToken = 0;
  const geocodeStatus = document.getElementById("geocode-status");

  const fetchElevation = async (lat, lon) => {
    const token = clickToken;
    try {
      const response = await fetch(`/api/elevation?lat=${lat}&lon=${lon}`);
      const result = await response.json();
      if (token !== clickToken || userTouchedAltitude) {
        return;
      }
      if (result.ok && altitudeInput) {
        altitudeInput.value = result.altitude_m;
        altitudeInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
    } catch (error) {
      // Ignore elevation failures silently.
    }
  };

  const fetchReverseGeocode = async (lat, lon) => {
    const token = clickToken;
    try {
      if (geocodeStatus) {
        geocodeStatus.textContent = "Finding location…";
      }
      const response = await fetch("/api/reverse_geocode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lat, lon }),
      });
      const result = await response.json();
      console.log("reverse geocode:", result);
      if (token !== clickToken) {
        return;
      }
      if (result.ok) {
        if (countryInput && !userTouchedCountry && result.country) {
          countryInput.value = result.country;
          countryInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        if (locationInput && !userTouchedLocation && result.location) {
          locationInput.value = result.location;
          locationInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        if (geocodeStatus) {
          geocodeStatus.textContent =
            result.source === "offline"
              ? "Couldn’t fetch location (approximate used)"
              : "Location found";
        }
      } else if (geocodeStatus) {
        geocodeStatus.textContent = "Couldn’t fetch location";
      }
    } catch (error) {
      // Ignore reverse geocode failures silently.
      if (geocodeStatus) {
        geocodeStatus.textContent = "Couldn’t fetch location";
      }
    }
  };

  const setMarker = (lat, lon) => {
    marker.setLatLng([lat, lon]);
  };

  map.on("click", async (event) => {
    const { lat, lng } = event.latlng;
    clickToken += 1;
    userTouchedCountry = false;
    userTouchedLocation = false;
    userTouchedAltitude = false;
    latInput.value = lat.toFixed(5);
    lonInput.value = lng.toFixed(5);
    setMarker(lat, lng);
    try {
      showLoading("Finding location…");
      await fetchReverseGeocode(lat.toFixed(5), lng.toFixed(5));
      showLoading("Fetching altitude…");
      await fetchElevation(lat.toFixed(5), lng.toFixed(5));
    } finally {
      hideLoading();
    }
  });

  const syncFromInputs = () => {
    const lat = parseFloat(latInput.value);
    const lon = parseFloat(lonInput.value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      setMarker(lat, lon);
    }
  };

  latInput?.addEventListener("change", syncFromInputs);
  lonInput?.addEventListener("change", syncFromInputs);
  altitudeInput?.addEventListener("input", (event) => {
    if (event.isTrusted) {
      userTouchedAltitude = true;
    }
  });
  countryInput?.addEventListener("input", (event) => {
    if (event.isTrusted) {
      userTouchedCountry = true;
    }
  });
  locationInput?.addEventListener("input", (event) => {
    if (event.isTrusted) {
      userTouchedLocation = true;
    }
  });

  const parseButton = document.getElementById("parse-maps");
  const linkInput = document.getElementById("maps-link");
  const status = document.getElementById("maps-status");
  if (parseButton && linkInput && status) {
    parseButton.addEventListener("click", async () => {
      status.textContent = "Parsing...";
      showLoading("Parsing link…");
      try {
        const response = await fetch("/api/parse_maps_link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: linkInput.value }),
        });
        const result = await response.json();
        if (result.ok) {
          status.textContent = "Coordinates updated.";
          clickToken += 1;
          userTouchedCountry = false;
          userTouchedLocation = false;
          userTouchedAltitude = false;
          latInput.value = result.lat.toFixed(5);
          lonInput.value = result.lon.toFixed(5);
          setMarker(result.lat, result.lon);
          map.setView([result.lat, result.lon], 7);
          showLoading("Finding location…");
          await fetchReverseGeocode(result.lat.toFixed(5), result.lon.toFixed(5));
          showLoading("Fetching altitude…");
          await fetchElevation(result.lat.toFixed(5), result.lon.toFixed(5));
        } else {
          status.textContent = result.error || "Unable to parse.";
        }
      } finally {
        hideLoading();
      }
    });
  }
};

const setupMapView = () => {
  const mapEl = document.getElementById("map-view");
  if (!mapEl || !window.coffeeMapData) return;

  const map = L.map(mapEl).setView([15, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
  }).addTo(map);

  const bounds = [];
  const ratingColors = {
    5: "#1d4ed8",
    4: "#3b82f6",
    3: "#cbd5e1",
    2: "#fca5a5",
    1: "#ef4444",
  };

  const flagForCountry = (country) => {
    if (!country || !window.countryFlags) return "";
    const flag = window.countryFlags[country];
    return flag ? `${flag} ` : "";
  };

  window.coffeeMapData.forEach((coffee) => {
    const lat = coffee.latitude;
    const lon = coffee.longitude;
    if (lat === null || lon === null) return;
    const rating = coffee.rating || 3;
    const color = ratingColors[rating] || ratingColors[3];
    const marker = L.circleMarker([lat, lon], {
      radius: 5,
      weight: 1,
      color,
      fillColor: color,
      fillOpacity: 0.85,
    }).addTo(map);
    bounds.push([lat, lon]);
    const details = [
      `<strong>${coffee.brand || "Unknown roaster"}</strong>`,
      `${coffee.varietal || ""}`.trim(),
      `${flagForCountry(coffee.country)}${coffee.country || ""}${
        coffee.location ? ` · ${coffee.location}` : ""
      }`,
      coffee.brew_style ? `Brew: ${coffee.brew_style}` : "",
      coffee.rating ? `Rating: ${coffee.rating}/5` : "",
      coffee.flavours ? `Flavours: ${coffee.flavours}` : "",
      coffee.altitude_m ? `Altitude: ${coffee.altitude_m} m` : "",
      coffee.id ? `<a class="popup-link" href="/log?entry_id=${coffee.id}">View entry</a>` : "",
    ]
      .filter(Boolean)
      .join("<br>");
    marker.bindPopup(details);
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [30, 30] });
  }

  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const div = document.createElement("div");
    div.className = "map-legend";
    div.innerHTML = `
      <div class="map-legend__title">Rating</div>
      <div class="map-legend__item"><span style="background:${ratingColors[5]}"></span>5</div>
      <div class="map-legend__item"><span style="background:${ratingColors[4]}"></span>4</div>
      <div class="map-legend__item"><span style="background:${ratingColors[3]}"></span>3</div>
      <div class="map-legend__item"><span style="background:${ratingColors[2]}"></span>2</div>
      <div class="map-legend__item"><span style="background:${ratingColors[1]}"></span>1</div>
    `;
    return div;
  };
  legend.addTo(map);
};

const setupAltitudeMap = () => {
  const mapEl = document.getElementById("altitude-map");
  if (!mapEl || !window.coffeeAltitudeData) return;

  const map = L.map(mapEl).setView([15, 0], 2);
  L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", {
    attribution:
      'Map data: © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM | Tiles: © <a href="https://opentopomap.org">OpenTopoMap</a>',
  }).addTo(map);

  const ratingColors = {
    5: "#1d4ed8",
    4: "#3b82f6",
    3: "#cbd5e1",
    2: "#fca5a5",
    1: "#ef4444",
  };

  const flagForCountry = (country) => {
    if (!country || !window.countryFlags) return "";
    const flag = window.countryFlags[country];
    return flag ? `${flag} ` : "";
  };

  const bounds = [];
  window.coffeeAltitudeData.forEach((coffee) => {
    const lat = coffee.latitude;
    const lon = coffee.longitude;
    if (lat === null || lon === null) return;
    const rating = coffee.rating || 3;
    const color = ratingColors[rating] || ratingColors[3];
    const marker = L.circleMarker([lat, lon], {
      radius: 5,
      weight: 1,
      color,
      fillColor: color,
      fillOpacity: 0.85,
    }).addTo(map);
    bounds.push([lat, lon]);
    const headline = `<strong>${coffee.brand || "Unknown roaster"}${
      coffee.varietal ? ` · ${coffee.varietal}` : ""
    }</strong>`;
    const location = `${flagForCountry(coffee.country)}${coffee.country || ""}${
      coffee.location ? ` · ${coffee.location}` : ""
    }`;
    const details = [
      headline,
      location,
      coffee.rating ? `Rating: ${coffee.rating} / 5` : "",
      coffee.altitude_m ? `Altitude: ⛰ ${coffee.altitude_m} m` : "",
      coffee.id ? `<a class="popup-link" href="/log?entry_id=${coffee.id}">View entry</a>` : "",
    ]
      .filter(Boolean)
      .join("<br>");
    marker.bindPopup(details);
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [30, 30] });
  }

  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const div = document.createElement("div");
    div.className = "map-legend";
    div.innerHTML = `
      <div class="map-legend__title">Topo view</div>
      <div class="map-legend__subtitle">Pins coloured by rating</div>
      <div class="map-legend__item"><span style="background:${ratingColors[5]}"></span>5</div>
      <div class="map-legend__item"><span style="background:${ratingColors[4]}"></span>4</div>
      <div class="map-legend__item"><span style="background:${ratingColors[3]}"></span>3</div>
      <div class="map-legend__item"><span style="background:${ratingColors[2]}"></span>2</div>
      <div class="map-legend__item"><span style="background:${ratingColors[1]}"></span>1</div>
    `;
    return div;
  };
  legend.addTo(map);
};

const setupOriginMaps = () => {
  const originMaps = document.querySelectorAll(".origin-map");
  if (!originMaps.length) return;

  const tileUrl = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
  const regions = [
    {
      name: "South America",
      bounds: [
        [-56, -82],
        [13, -34],
      ],
    },
    {
      name: "North America",
      bounds: [
        [7, -170],
        [72, -50],
      ],
    },
    {
      name: "Europe",
      bounds: [
        [35, -25],
        [71, 40],
      ],
    },
    {
      name: "Africa",
      bounds: [
        [-35, -20],
        [37, 52],
      ],
    },
    {
      name: "Asia",
      bounds: [
        [5, 40],
        [77, 150],
      ],
    },
    {
      name: "Oceania",
      bounds: [
        [-50, 110],
        [10, 180],
      ],
    },
  ];

  const ratingColors = {
    5: "#1d4ed8",
    4: "#3b82f6",
    3: "#cbd5e1",
    2: "#fca5a5",
    1: "#ef4444",
  };

  const findRegionBounds = (lat, lon) => {
    return regions.find((region) => {
      const [[minLat, minLon], [maxLat, maxLon]] = region.bounds;
      return lat >= minLat && lat <= maxLat && lon >= minLon && lon <= maxLon;
    })?.bounds;
  };

  const initOriginMap = (el) => {
    if (el.dataset.ready === "true") return;
    const lat = parseFloat(el.dataset.lat);
    const lon = parseFloat(el.dataset.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

    const map = L.map(el, {
      zoomControl: false,
      attributionControl: true,
      scrollWheelZoom: false,
      dragging: false,
      doubleClickZoom: false,
      boxZoom: false,
      keyboard: false,
      tap: false,
    });
    L.tileLayer(tileUrl, {
      attribution: "© OpenStreetMap",
    }).addTo(map);

    const bounds = findRegionBounds(lat, lon);
    if (bounds) {
      map.fitBounds(bounds, { padding: [16, 16] });
      map.setZoom(map.getZoom() + 1);
    } else {
      map.setView([lat, lon], 5);
    }

    const rating = parseInt(el.dataset.rating, 10) || 3;
    const color = ratingColors[rating] || ratingColors[3];
    L.circleMarker([lat, lon], {
      radius: 4,
      weight: 1,
      color,
      fillColor: color,
      fillOpacity: 0.85,
    }).addTo(map);

    const entryId = el.dataset.id;
    if (entryId) {
      const goToMap = () => {
        window.location.href = `/map?entry_id=${entryId}`;
      };
      el.addEventListener("click", goToMap);
      el.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          goToMap();
        }
      });
    }

    el.dataset.ready = "true";
  };

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          initOriginMap(entry.target);
          observer.unobserve(entry.target);
        }
      });
    },
    { rootMargin: "100px" }
  );

  originMaps.forEach((el) => observer.observe(el));
};

document.addEventListener("DOMContentLoaded", () => {
  setupAutocomplete();
  setupGrindSettings();
  setupAddMap();
  setupMapView();
  setupAltitudeMap();
  setupOriginMaps();
});
