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
      if (typeof optionValue === "string") {
        option.value = optionValue;
        option.textContent = optionValue;
      } else {
        option.value = optionValue.value;
        option.textContent = optionValue.label;
      }
      grindSetting.appendChild(option);
    });
  };

  grinder.addEventListener("change", updateOptions);
};

const setupBagSelector = () => {
  const selector = document.getElementById("bag-selector");
  const bagIdInput = document.getElementById("bag-id");
  const toggle = document.getElementById("create-bag-toggle");
  const panel = document.getElementById("new-bag-panel");
  if (!selector || !bagIdInput || !window.coffeeLogConfig) return;

  const bagOptions = window.coffeeLogConfig.bagOptions || [];
  const labels = bagOptions.map((bag) => ({
    id: String(bag.id),
    label: `${bag.coffee_name} — ${bag.brand}`,
  }));

  const syncSelection = () => {
    const match = labels.find((item) => item.label === selector.value.trim());
    bagIdInput.value = match ? match.id : "";
  };

  const togglePanel = () => {
    const active = toggle?.checked;
    if (panel) {
      panel.style.display = active ? "block" : "none";
    }
    if (active) {
      bagIdInput.value = "";
    } else {
      syncSelection();
    }
  };

  selector.addEventListener("change", syncSelection);
  selector.addEventListener("input", syncSelection);
  toggle?.addEventListener("change", togglePanel);

  if (selector.dataset.selectedId) {
    const preset = labels.find((item) => item.id === selector.dataset.selectedId);
    if (preset) {
      selector.value = preset.label;
      bagIdInput.value = preset.id;
    }
  }

  if (!bagIdInput.value) {
    if (toggle) {
      toggle.checked = true;
    }
  }
  togglePanel();
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
  const markersById = {};
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
    if (coffee.id) {
      markersById[coffee.id] = marker;
    }
    bounds.push([lat, lon]);
    const title = `${coffee.coffee_name || "Untitled bag"}`;
    const brandLine = `${coffee.brand || "Unknown roaster"}${
      coffee.varietal ? ` · ${coffee.varietal}` : ""
    }`;
    const locationLine = `${flagForCountry(coffee.country)}${coffee.country || ""}${
      coffee.location ? ` · ${coffee.location}` : ""
    }`;
    const metaLine = [
      coffee.brew_style ? coffee.brew_style : "",
      coffee.rating ? `Rating: ${coffee.rating} / 5` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    const altitudeLine = coffee.altitude_m ? `⛰ ${coffee.altitude_m} m` : "";
    const linkLine = coffee.id
      ? `<a class="popup-link" href="/log?entry_id=${coffee.id}">View entry</a>`
      : "";
    const details = `
      <div class="popup-card">
        <div class="popup-title">${title}</div>
        ${brandLine ? `<div class="popup-sub">${brandLine}</div>` : ""}
        ${locationLine ? `<div class="popup-sub">${locationLine}</div>` : ""}
        ${metaLine ? `<div class="popup-meta">${metaLine}</div>` : ""}
        ${altitudeLine ? `<div class="popup-altitude">${altitudeLine}</div>` : ""}
        ${linkLine ? `<div class="popup-footer">${linkLine}</div>` : ""}
      </div>
    `;
    marker.bindPopup(details);
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [30, 30] });
  }

  const params = new URLSearchParams(window.location.search);
  const entryId = params.get("entry_id") || window.latestBrewId;
  if (entryId && markersById[entryId]) {
    const marker = markersById[entryId];
    const position = marker.getLatLng();
    map.setView(position, 7, { animate: true });
    marker.openPopup();
    const ring = L.circleMarker(position, {
      radius: 10,
      weight: 1,
      color: "rgba(197, 164, 107, 0.6)",
      fillColor: "rgba(197, 164, 107, 0.15)",
      fillOpacity: 0.4,
    }).addTo(map);
    setTimeout(() => {
      map.removeLayer(ring);
    }, 1600);
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

const setupAltitudeChart = () => {
  const chartEl = document.getElementById("altitude-chart");
  if (!chartEl || !window.coffeeAltitudeData || !window.Chart) return;

  const ratingColors = {
    5: "rgba(29, 78, 216, 0.7)",
    4: "rgba(59, 130, 246, 0.7)",
    3: "rgba(148, 163, 184, 0.6)",
    2: "rgba(252, 165, 165, 0.6)",
    1: "rgba(239, 68, 68, 0.7)",
  };

  const jitter = (id) => {
    const seed = Number(id) % 10;
    return (seed - 5) * 0.04;
  };

  const points = window.coffeeAltitudeData
    .filter((coffee) => Number.isFinite(coffee.altitude_m))
    .map((coffee) => {
      const rating = coffee.rating || 3;
      return {
        x: rating + jitter(coffee.id || 0),
        y: coffee.altitude_m,
        r: rating,
        id: coffee.id,
        coffee_name: coffee.coffee_name,
        brand: coffee.brand,
        varietal: coffee.varietal,
        country: coffee.country,
        location: coffee.location,
        altitude: coffee.altitude_m,
      };
    });

  const chart = new Chart(chartEl, {
    type: "scatter",
    data: {
      datasets: [
        {
          data: points,
          pointRadius: 3,
          pointHoverRadius: 4,
          pointBackgroundColor: (ctx) => ratingColors[ctx.raw?.r || 3],
          pointBorderColor: "rgba(16, 24, 40, 0.15)",
        },
      ],
    },
    options: {
      animation: false,
      scales: {
        x: {
          min: 0.5,
          max: 5.5,
          ticks: {
            stepSize: 1,
            callback: (value) => `${value} / 5`,
          },
          title: {
            display: true,
            text: "Rating",
          },
          grid: {
            color: "rgba(16, 24, 40, 0.06)",
          },
        },
        y: {
          title: {
            display: true,
            text: "Altitude (m)",
          },
          grid: {
            color: "rgba(16, 24, 40, 0.06)",
          },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const raw = ctx.raw || {};
              const location = [raw.country, raw.location].filter(Boolean).join(", ");
              return [
                `${raw.coffee_name || "Untitled bag"}`,
                `${raw.brand || "Unknown roaster"}${raw.varietal ? ` · ${raw.varietal}` : ""}`,
                location,
                `Altitude: ${raw.altitude} m`,
                `Rating: ${raw.r} / 5`,
              ].filter(Boolean);
            },
          },
        },
      },
      onClick: (_event, elements) => {
        if (!elements.length) return;
        const raw = elements[0].element.$context.raw;
        if (raw?.id) {
          window.location.href = `/log?entry_id=${raw.id}`;
        }
      },
    },
  });

  chartEl.dataset.ready = "true";
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
  setupBagSelector();
  setupAddMap();
  setupMapView();
  setupAltitudeChart();
  setupOriginMaps();
});
