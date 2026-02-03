const debounce = (fn, wait = 250) => {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), wait);
  };
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
  const mapEl = document.getElementById("add-map");
  if (!mapEl) return;

  const map = L.map(mapEl).setView([10, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
  }).addTo(map);

  const marker = L.marker([10, 0], { draggable: false }).addTo(map);
  const latInput = document.getElementById("latitude");
  const lonInput = document.getElementById("longitude");
  const altitudeInput = document.getElementById("altitude");

  const fetchElevation = async (lat, lon) => {
    try {
      const response = await fetch(`/api/elevation?lat=${lat}&lon=${lon}`);
      const result = await response.json();
      if (result.ok && altitudeInput) {
        altitudeInput.value = result.altitude_m;
      }
    } catch (error) {
      // Ignore elevation failures silently.
    }
  };

  const setMarker = (lat, lon) => {
    marker.setLatLng([lat, lon]);
  };

  map.on("click", (event) => {
    const { lat, lng } = event.latlng;
    latInput.value = lat.toFixed(5);
    lonInput.value = lng.toFixed(5);
    setMarker(lat, lng);
    fetchElevation(lat.toFixed(5), lng.toFixed(5));
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

  const parseButton = document.getElementById("parse-maps");
  const linkInput = document.getElementById("maps-link");
  const status = document.getElementById("maps-status");
  if (parseButton && linkInput && status) {
    parseButton.addEventListener("click", async () => {
      status.textContent = "Parsing...";
      const response = await fetch("/api/parse_maps_link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: linkInput.value }),
      });
      const result = await response.json();
      if (result.ok) {
        status.textContent = "Coordinates updated.";
        latInput.value = result.lat.toFixed(5);
        lonInput.value = result.lon.toFixed(5);
        setMarker(result.lat, result.lon);
        map.setView([result.lat, result.lon], 7);
        fetchElevation(result.lat.toFixed(5), result.lon.toFixed(5));
      } else {
        status.textContent = result.error || "Unable to parse.";
      }
    });
  }
};

const setupMapView = () => {
  const mapEl = document.getElementById("map");
  if (!mapEl || !window.coffeeMapData) return;

  const map = L.map(mapEl).setView([15, 0], 2);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
  }).addTo(map);

  const bounds = [];
  window.coffeeMapData.forEach((coffee) => {
    const lat = coffee.latitude;
    const lon = coffee.longitude;
    if (lat === null || lon === null) return;
    const marker = L.marker([lat, lon]).addTo(map);
    bounds.push([lat, lon]);
    const details = [
      `<strong>${coffee.brand || "Unknown roaster"}</strong>`,
      `${coffee.varietal || ""} ${coffee.origin_region || ""}`.trim(),
      `${coffee.country || ""}${coffee.location ? ` · ${coffee.location}` : ""}`,
      coffee.brew_style ? `Brew: ${coffee.brew_style}` : "",
      coffee.rating ? `Rating: ${coffee.rating}/5` : "",
      coffee.flavours ? `Flavours: ${coffee.flavours}` : "",
      coffee.altitude_m ? `Altitude: ${coffee.altitude_m} m` : "",
    ]
      .filter(Boolean)
      .join("<br>");
    marker.bindPopup(details);
  });

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [30, 30] });
  }
};

document.addEventListener("DOMContentLoaded", () => {
  setupAutocomplete();
  setupGrindSettings();
  setupAddMap();
  setupMapView();
});
