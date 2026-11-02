(async function () {
  const showFatal = (e) => {
    const box = document.getElementById("detail");
    if (box) box.innerHTML = '<h2>The page could not load its data</h2><p>' + String((e && e.message) || e).replace(/</g, "&lt;") +
      '</p><p>Check that the server is still running in the terminal, then run <b>python pipeline/export_site_data.py</b> and refresh the page with Ctrl + F5. ' +
      'If it still fails, press F12, open the Console tab, and read the first red message.</p>';
  };
  try { await (async function () {
  const $ = (id) => document.getElementById(id);
  const get = async (url) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  };
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const COLORS = { kerala: "#5fc59a", karnataka: "#f7c35f", tamilnadu: "#f5906d" };

  const has = (v) => v !== null && v !== undefined && !Number.isNaN(v);
  const vals = (a) => (a || []).filter(has);
  const sum = (a) => vals(a).reduce((s, x) => s + x, 0);
  const avg = (a) => { const v = vals(a); return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null; };
  const full = (a) => a.length > 0 && a.every(has);
  const fmt = (v, d = 1, u = "") => (has(v) ? v.toFixed(d) + u : "n/a");
  const sgn = (v, d = 2) => (has(v) ? (v > 0 ? "+" : "") + v.toFixed(d) : "n/a");
  const idxOf = (a, best) => { let k = -1; a.forEach((v, i) => { if (has(v) && (k < 0 || best(v, a[k]))) k = i; }); return k; };
  // "(Jan-Aug)" when a list does not cover the whole year
  const span = (a) => { const k = a.map((v, i) => (has(v) ? i : -1)).filter((i) => i >= 0); return k.length && k.length < 12 ? `${FULL[k[0]]} to ${FULL[k[k.length - 1]]}` : ""; };

  const ov = await get("/api/overview/");
  const geos = await Promise.all(ov.states.map((s) => get(`/api/geojson/${s.slug}/`)));
  const fcs = await Promise.all(ov.states.map((s) => get(`/api/forecast/${s.slug}/`)));
  const forecast = {};
  ov.states.forEach((s, i) => fcs[i].districts.forEach((d) => { forecast[s.slug + "|" + d.name] = d; }));

  // ---- geometry helpers ----
  function ringStats(ring) {
    let a = 0, cx = 0, cy = 0;
    for (let i = 0; i < ring.length - 1; i++) {
      const [x0, y0] = ring[i], [x1, y1] = ring[i + 1], f = x0 * y1 - x1 * y0;
      a += f; cx += (x0 + x1) * f; cy += (y0 + y1) * f;
    }
    if (Math.abs(a) < 1e-12) return { area: 0, lon: avg(ring.map((p) => p[0])), lat: avg(ring.map((p) => p[1])) };
    return { area: Math.abs(a / 2), lon: cx / (3 * a), lat: cy / (3 * a) };
  }
  function geomStats(g) {
    const rings = g.type === "Polygon" ? [g.coordinates[0]] : g.coordinates.map((p) => p[0]);
    return rings.map(ringStats).sort((a, b) => b.area - a.area)[0];
  }

  const features = [], bounds = {};
  ov.states.forEach((s, i) => {
    let minLat = 99, maxLat = -99, minLon = 999, maxLon = -999;
    geos[i].features.forEach((f) => {
      features.push({ slug: s.slug, state: s.name, name: f.properties.district, key: s.slug + "|" + f.properties.district, ...geomStats(f.geometry) });
      const walk = (c) => (typeof c[0] === "number" ? (minLon = Math.min(minLon, c[0]), maxLon = Math.max(maxLon, c[0]), minLat = Math.min(minLat, c[1]), maxLat = Math.max(maxLat, c[1])) : c.forEach(walk));
      walk(f.geometry.coordinates);
    });
    bounds[s.slug] = [[minLat, minLon], [maxLat, maxLon]];
    const n = $("n-" + s.slug);
    if (n) n.textContent = `${geos[i].features.length} districts`;
  });
  const featByKey = Object.fromEntries(features.map((f) => [f.key, f]));

  // ---- drop-downs ----
  const dsel = $("district");
  dsel.add(new Option("Choose a district…", ""));
  ov.states.forEach((s) => {
    const g = document.createElement("optgroup");
    g.label = s.name;
    features.filter((f) => f.slug === s.slug).map((f) => f.name).sort().forEach((n) => g.appendChild(new Option(n, s.slug + "|" + n)));
    dsel.appendChild(g);
  });
  const fcYears = [...new Set(Object.values(forecast).flatMap((d) => Object.keys(d.forecast || {}).map((k) => Number(k.slice(0, 4)))))]
    .filter((y) => !ov.years.includes(y)).sort((a, b) => b - a);
    $("year").add(new Option("Select year", ""));
  fcYears.forEach((y) => $("year").add(new Option(`${y}`, String(y))));
  [...ov.years].reverse().forEach((y) => $("year").add(new Option(y, String(y))));
  $("year").value = "";

  // ---- one separate map for each state (drawn from the district boundaries only, no map tiles) ----
  let selected = "";
  const MAPS = {};
  function paint(key) {
    if (!key) return;
    const m = MAPS[key.split("|")[0]], l = m && m.layers[key];
    if (!l) return;
    if (key === selected) { l.setStyle({ weight: 4, color: "#1b1b1b", fillOpacity: 0.97 }); if (l.bringToFront) l.bringToFront(); }
    else l.setStyle({ weight: 1.5, color: "#ffffff", fillOpacity: 0.85 });
  }
  function declutter(slug) {                 // bigger districts keep their name; a name that would overlap another is hidden until you zoom in
    const m = MAPS[slug];
    if (!m) return;
    const placed = [];
    [...m.labels].sort((a, b) => (b.f.key === selected) - (a.f.key === selected)).forEach(({ f, marker }) => {
      const p = m.map.latLngToContainerPoint([f.lat, f.lon]);
      const w = f.name.length * (f.key === selected ? 7.4 : 5.9) + 8, h = 14;
      const box = [p.x - w / 2, p.y - h / 2, p.x + w / 2, p.y + h / 2];
      const free = !placed.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]);
      const el = marker.getElement && marker.getElement();
      if (el) { el.style.visibility = free || f.key === selected ? "visible" : "hidden"; el.classList.toggle("sel", f.key === selected); }
      if (free || f.key === selected) placed.push(box);
    });
  }
  ov.states.forEach((s, i) => {
    const map = L.map("map-" + s.slug, { zoomSnap: 0.25, zoomDelta: 0.5, scrollWheelZoom: false, attributionControl: false });
    const layers = {};
    L.geoJSON(geos[i], {
      style: () => ({ fillColor: COLORS[s.slug], fillOpacity: 0.85, color: "#ffffff", weight: 1.5 }),
      onEachFeature: (f, l) => {
        const key = s.slug + "|" + f.properties.district;
        layers[key] = l;
        l.bindTooltip(f.properties.district, { sticky: true });
        l.on("click", () => selectDistrict(key, true));
        l.on("mouseover", () => { if (key !== selected) l.setStyle({ weight: 3, fillOpacity: 0.97 }); });
        l.on("mouseout", () => paint(key));
      },
    }).addTo(map);
    map.fitBounds(bounds[s.slug]);
    const labels = features.filter((f) => f.slug === s.slug).sort((a, b) => b.area - a.area).map((f) => ({
      f, marker: L.marker([f.lat, f.lon], { icon: L.divIcon({ className: "dlabel", html: `<span>${esc(f.name)}</span>`, iconSize: [0, 0] }), interactive: false, keyboard: false }).addTo(map),
    }));
    MAPS[s.slug] = { map, layers, labels };
    map.on("zoomend moveend", () => declutter(s.slug));
    setTimeout(() => declutter(s.slug), 60);
  });

  // ---- data of the chosen district ----
  const climateCache = {}, live = {};
  const climateFor = async (key) => {
    if (!climateCache[key]) {
      const [slug, name] = key.split("|");
      climateCache[key] = await get(`/api/climate/${slug}/?name=${encodeURIComponent(name)}`);
    }
    return climateCache[key];
  };

  async function selectDistrict(key, fromMap) {
    const old = selected;
    selected = key || "";
    dsel.value = selected;
    if (old) { paint(old); declutter(old.split("|")[0]); }
    if (selected) { paint(selected); declutter(selected.split("|")[0]); }
    await renderDetail();
    if (selected) {
      loadLive(selected);
      const d = $("detail");
      if (fromMap && d.scrollIntoView) d.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  const tile = (cls, ic, label, value, note) =>
    `<div class="tile ${cls}"><div class="ic">${ic}</div><div><span>${label}</span><b>${value}</b><em>${note || ""}</em></div></div>`;

  function chartSvg(rain, tmax, tmin, fl) {
    fl = fl || [];
    const W = 640, H = 290, Lm = 50, Rm = 46, T = 14, B = 34, iw = W - Lm - Rm, ih = H - T - B;
    const nice = (v) => { const raw = Math.max(v, 1) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))); return [1, 2, 2.5, 5, 10].find((s) => s * mag >= raw) * mag * 4; };
    const maxR = nice(Math.max(...vals(rain), 1));
    const temps = [...vals(tmax), ...vals(tmin)];
    const tLo = Math.floor(Math.min(...temps, 100) - 1), tHi = Math.ceil(Math.max(...temps, -100) + 1);
    const x = (i) => Lm + ((i + 0.5) * iw) / 12;
    const yR = (v) => T + ih - (v / maxR) * ih;
    const yT = (v) => T + ih - ((v - tLo) / (tHi - tLo || 1)) * ih;
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Monthly rainfall and temperature">`;
    for (let k = 0; k <= 4; k++) {
      const yy = T + (ih * k) / 4;
      s += `<line x1="${Lm}" x2="${W - Rm}" y1="${yy}" y2="${yy}" stroke="#efd3a0"/>` +
           `<text x="${Lm - 6}" y="${yy + 3}" font-size="10" text-anchor="end" fill="#2a6f97">${Math.round(maxR * (1 - k / 4))}</text>` +
           `<text x="${W - Rm + 6}" y="${yy + 3}" font-size="10" fill="#b23a1d">${(tLo + ((tHi - tLo) * (4 - k)) / 4).toFixed(0)}</text>`;
    }
    s += `<text x="${Lm - 6}" y="${T - 3}" font-size="10" text-anchor="end" fill="#2a6f97">mm</text><text x="${W - Rm + 6}" y="${T - 3}" font-size="10" fill="#b23a1d">°C</text>`;
    const bw = (iw / 12) * 0.56;
    rain.forEach((v, i) => { if (has(v)) s += `<rect x="${x(i) - bw / 2}" y="${yR(v)}" width="${bw}" height="${T + ih - yR(v)}" rx="3" fill="#6bb6e8" opacity="${fl[i] ? 0.4 : 1}"/>`; });
    const line = (a, col) => {
      const pts = a.map((v, i) => (has(v) ? `${x(i).toFixed(1)},${yT(v).toFixed(1)}` : null)).filter(Boolean);
      return (pts.length > 1 ? `<polyline fill="none" stroke="${col}" stroke-width="2.5" points="${pts.join(" ")}"/>` : "") +
             a.map((v, i) => (has(v) ? `<circle cx="${x(i).toFixed(1)}" cy="${yT(v).toFixed(1)}" r="3.5" fill="${fl[i] ? "#fff" : col}" stroke="${col}" stroke-width="2"/>` : "")).join("");
    };
    s += line(tmax, "#e4572e") + line(tmin, "#2a9d8f");
    MONTHS.forEach((m, i) => { s += `<text x="${x(i)}" y="${H - 12}" font-size="11" text-anchor="middle" fill="#6b5846">${m}</text>`; });
    return s + "</svg>";
  }

  // ---- forecast (from your own model) ----
  function springOutlook(fc) {
    if (!fc || !fc.forecast) return null;
    const years = [...new Set(Object.keys(fc.forecast).map((k) => k.slice(0, 4)))].sort().reverse();
    for (const y of years) {
      const rows = ["03", "04", "05"].map((m) => fc.forecast[`${y}-${m}`]);
      if (rows.every(Boolean)) return { year: y, v: avg(rows.map((r) => r[0])), lo: avg(rows.map((r) => r[1])), hi: avg(rows.map((r) => r[2])) };
    }
    return null;
  }
  function forecastSvg(f, keys) {
    const W = 640, H = 280, Lm = 44, Rm = 14, T = 14, B = 44, iw = W - Lm - Rm, ih = H - T - B;
    const all = keys.flatMap((k) => [f[k][1], f[k][2], f[k][4], f[k][5]]);
    const lo = Math.floor(Math.min(...all) - 1), hi = Math.ceil(Math.max(...all) + 1);
    const x = (i) => Lm + ((i + 0.5) * iw) / keys.length, y = (v) => T + ih - ((v - lo) / (hi - lo || 1)) * ih;
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Forecast of monthly daily high and low temperature">`;
    for (let k = 0; k <= 4; k++) {
      const yy = T + (ih * k) / 4;
      s += `<line x1="${Lm}" x2="${W - Rm}" y1="${yy}" y2="${yy}" stroke="#efd3a0"/><text x="${Lm - 6}" y="${yy + 3}" font-size="10" text-anchor="end" fill="#6b5846">${(hi - ((hi - lo) * k) / 4).toFixed(0)}</text>`;
    }
    s += `<text x="${Lm - 6}" y="${T - 3}" font-size="10" text-anchor="end" fill="#6b5846">°C</text>`;
    const band = (a, b, col) => {
      const up = keys.map((k, i) => `${x(i).toFixed(1)},${y(f[k][b]).toFixed(1)}`);
      const dn = keys.map((k, i) => `${x(i).toFixed(1)},${y(f[k][a]).toFixed(1)}`).reverse();
      return `<polygon points="${[...up, ...dn].join(" ")}" fill="${col}"/>`;
    };
    const line = (idx, col) => `<polyline fill="none" stroke="${col}" stroke-width="2.5" points="${keys.map((k, i) => `${x(i).toFixed(1)},${y(f[k][idx]).toFixed(1)}`).join(" ")}"/>` +
      keys.map((k, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(f[k][idx]).toFixed(1)}" r="3" fill="${col}"/>`).join("");
    s += band(1, 2, "rgba(228,87,46,.18)") + band(4, 5, "rgba(42,157,143,.18)") + line(0, "#e4572e") + line(3, "#2a9d8f");
    keys.forEach((k, i) => {
      const [yy, mm] = k.split("-").map(Number);
      s += `<text x="${x(i)}" y="${H - 26}" font-size="10" text-anchor="middle" fill="#6b5846">${MONTHS[mm - 1]}</text>`;
      if (i === 0 || mm === 1) s += `<text x="${x(i)}" y="${H - 12}" font-size="10" font-weight="700" text-anchor="middle" fill="#2b1a0e">${yy}</text>`;
    });
    return s + "</svg>";
  }
  function forecastHtml(fc) {
    const keys = fc ? Object.keys(fc.forecast || {}).sort() : [];
    if (!keys.length) return "";
    const fcell = (v, d, rng) => {
      if (!has(v)) return "<td>n/a</td>";
      const r = rng && has(rng[0]) && has(rng[1]) ? `<span class="rng"> (${rng[0].toFixed(d)} to ${rng[1].toFixed(d)})</span>` : "";
      return `<td class="f">${v.toFixed(d)}${r}</td>`;
    };
    const rows = keys.map((k) => {
      const v = fc.forecast[k], [yy, mm] = k.split("-").map(Number);
      const rt = fc.rain_typical && fc.rain_typical[mm - 1], ixm = ov.index_forecast && ov.index_forecast[k];
      return `<tr><td>${MONTHS[mm - 1]} ${yy}</td>${fcell(rt ? rt[0] : null, 1, rt ? [rt[1], rt[2]] : null)}${fcell(v[0], 1, [v[1], v[2]])}${fcell(v[3], 1, [v[4], v[5]])}` +
             `${fcell(ixm ? ixm[0] : null, 2, ixm ? [ixm[1], ixm[2]] : null)}` + (ov.indices.dmi ? fcell(ixm ? ixm[3] : null, 2, ixm ? [ixm[4], ixm[5]] : null) : "") + "</tr>";
    }).join("");
    return '<p class="group fc">Forecast for the months ahead</p>' +
      `<div class="chartwrap">${forecastSvg(fc.forecast, keys)}</div>` +
      '<p class="chartlegend"><span><i style="background:#e4572e"></i>Expected daily high (°C)</span><span><i style="background:#2a9d8f"></i>Expected daily low (°C)</span><span><i style="background:#f3d3c7"></i>Shaded: likely range</span></p>' +
      '<div class="table-wrap"><table><thead><tr><th>Month</th><th>Rain (mm)</th><th>High (°C)</th><th>Low (°C)</th><th>El Niño</th>' + (ov.indices.dmi ? "<th>IOD</th>" : "") + "</tr></thead><tbody>" + rows + "</tbody></table></div>" +
      `<p class="small">High and low: forecast from our model. El Niño and IOD: forecast from our statistical model. Rain: the typical value of past years, not a forecast. The ranges in brackets cover about 80% of the errors seen in past years. ${esc(ov.forecast_note)}</p>`;
  }

  // ---- the details of the chosen district and year ----
  async function renderDetail() {
    const box = $("detail");
    if (!selected) {
      box.innerHTML = '<div class="welcome"><div class="sunico">☀️</div><h2>Pick a district</h2>' +
        "<p>Click a district on one of the three maps, or choose one from the District menu, then choose a year. You will see its real temperature, rainfall and the climate indicators that affect temperature. Future months show the forecast from our model.</p></div>";
      return;
    }
    const key = selected, year = $("year").value;
    const c = await climateFor(key);
    if (key !== selected || year !== $("year").value) return;       // the user chose something else meanwhile
    const f = featByKey[key], fc = forecast[key];
    const isFc = !c.years.includes(Number(year));                    // a year with no measured data: show the forecast
    const mk = (m) => `${year}-${String(m + 1).padStart(2, "0")}`;
    const fv = (m, idx) => { const v = fc && fc.forecast && fc.forecast[mk(m)]; return v ? v[idx] : null; };
    const rt = (m) => (fc && fc.rain_typical && fc.rain_typical[m]) || null;
    const ix = (m) => (ov.index_forecast && ov.index_forecast[mk(m)]) || null;
    let rain, tmax, tmin, oniArr, dmiArr;       // measured values (for a forecast year: the forecast), used for the yearly figures
    if (isFc) {
      tmax = MONTHS.map((_, m) => fv(m, 0)); tmin = MONTHS.map((_, m) => fv(m, 3));
      rain = MONTHS.map((_, m) => (rt(m) ? rt(m)[0] : null));
      oniArr = MONTHS.map((_, m) => (ix(m) ? ix(m)[0] : null)); dmiArr = MONTHS.map((_, m) => (ix(m) ? ix(m)[3] : null));
      if (!vals(tmax).length) {
        box.innerHTML = `<h2 class="dn">${esc(f.name)}</h2><p class="sub2">${esc(f.state)} · ${year}</p><p>No forecast is available for ${year}.</p>`;
        return;
      }
    } else {
      const i = c.years.indexOf(Number(year));
      rain = c.rain[i] || []; tmax = c.tmax[i] || []; tmin = c.tmin[i] || [];
      oniArr = (ov.indices.oni && ov.indices.oni[year]) || []; dmiArr = (ov.indices.dmi && ov.indices.dmi[year]) || [];
    }

    // values shown in the month-by-month chart and table: measured where we have them, otherwise forecast (marked)
    const F = MONTHS.map(() => ({})), R = MONTHS.map(() => ({}));
    const dRain = rain.slice(), dMax = tmax.slice(), dMin = tmin.slice(), dOni = oniArr.slice(), dDmi = dmiArr.slice();
    MONTHS.forEach((_, m) => {
      const fm = fc && fc.forecast && fc.forecast[mk(m)];
      if (isFc || (!has(tmax[m]) && !has(tmin[m]) && !has(rain[m]))) {
        if (fm) { dMax[m] = fm[0]; dMin[m] = fm[3]; R[m].hi = [fm[1], fm[2]]; R[m].lo = [fm[4], fm[5]]; F[m].hi = F[m].lo = true; }
        if (rt(m)) { dRain[m] = rt(m)[0]; R[m].rain = [rt(m)[1], rt(m)[2]]; F[m].rain = true; }
      }
      const v = ix(m);
      if (v && (isFc || !has(oniArr[m])) && has(v[0])) { dOni[m] = v[0]; R[m].oni = [v[1], v[2]]; F[m].oni = true; }
      if (v && (isFc || !has(dmiArr[m])) && has(v[3])) { dDmi[m] = v[3]; R[m].dmi = [v[4], v[5]]; F[m].dmi = true; }
    });
    const anyF = F.some((x) => Object.keys(x).length);

    const part = isFc ? "" : (span(tmax) || span(rain));             // for example "January to September" when the year is not complete
    const oniAvg = avg(oniArr), dmiAvg = avg(dmiArr);
    const phase = !has(oniAvg) ? "" : oniAvg >= 0.5 ? "El Niño" : oniAvg <= -0.5 ? "La Niña" : "Neutral";
    const hot = idxOf(tmax, (a, b) => a > b);
    const aMax = avg(tmax), aMin = avg(tmin);
    const sub = (a, from, to) => a.slice(from, to);
    const spring = springOutlook(fc);
    const per = (note) => [note, part, isFc ? "forecast" : ""].filter(Boolean).join(", ");

    let a = '<p class="group">Now and ahead</p><div class="tiles">' +
      tile("t-now", "📍", "Temperature right now", '<span id="live-v" style="display:inline;font-size:inherit;letter-spacing:0">loading…</span>', '<span id="live-t" style="display:inline;font-weight:400;letter-spacing:0">live, from Open-Meteo</span>') +
      (spring ? tile("t-fc", "🔮", `Forecast: March to May ${spring.year}`, fmt(spring.v, 1, " °C"), `average daily high, range ${spring.lo.toFixed(1)} to ${spring.hi.toFixed(1)} °C`) : "") + "</div>";
    a += `<p class="group">Temperature in ${year}${isFc ? " (forecast)" : ""}</p><div class="tiles">` +
      tile("t-temp", "☀️", "Average daily high", fmt(aMax, 1, " °C"), per("average of the monthly highs")) +
      tile("t-temp", "🌙", "Average daily low", fmt(aMin, 1, " °C"), per("average of the monthly lows")) +
      tile("t-temp", "🌡️", "Average temperature", has(aMax) && has(aMin) ? fmt((aMax + aMin) / 2, 1, " °C") : "n/a", per("mean of daily high and low")) +
      tile("t-temp", "↕️", "Day-night range", has(aMax) && has(aMin) ? fmt(aMax - aMin, 1, " °C") : "n/a", per("daily high minus daily low")) +
      tile("t-temp", "🔥", "Hottest month", hot >= 0 ? fmt(tmax[hot], 1, " °C") : "n/a", hot >= 0 ? FULL[hot] + (isFc ? " (daily high, forecast)" : " (daily high)") : "") +
      tile("t-temp", "🌴", "Summer: March to May", full(sub(tmax, 2, 5)) ? fmt(avg(sub(tmax, 2, 5)), 1, " °C") : "n/a", isFc ? "average daily high, forecast" : "average daily high") + "</div>";

    const typ = isFc ? '<br><span class="rng">typical, not a forecast</span>' : "";
    const row = (name, value, why) => `<tr><td>${name}</td><td><b>${value}</b></td><td class="why">${why}</td></tr>`;
    const oniCell = !has(oniAvg) ? "n/a" : `${sgn(oniAvg)}${phase ? " · " + phase : ""}` +
      (isFc ? '<br><span class="rng">forecast, year average</span>' : span(oniArr) ? `<br><span class="rng">${span(oniArr)}</span>` : "");
    const dmiCell = !has(dmiAvg) ? "n/a" : `${sgn(dmiAvg)}` + (isFc ? '<br><span class="rng">forecast, year average</span>' : span(dmiArr) ? `<br><span class="rng">${span(dmiArr)}</span>` : "");
    a += `<p class="group">Indicators that affect temperature, ${year}</p><div class="table-wrap"><table class="ind"><thead><tr><th>Indicator</th><th>Value</th><th>How it affects temperature</th></tr></thead><tbody>` +
      row("El Niño index (ONI)", oniCell, "A positive index (El Niño, +0.5 or more) usually brings hotter springs to South India.") +
      (ov.indices.dmi ? row("Indian Ocean Dipole (DMI)", dmiCell, "Changes the strength of the monsoon and the rainfall, which changes the daily highs.") : "") +
      row("Total rainfall", (vals(rain).length ? fmt(sum(rain), 0, " mm") : "n/a") + (part ? `<br><span class="rng">${part}</span>` : "") + typ, "More rain and cloud usually lower the daily high.") +
      row("Southwest monsoon (June to September)", (full(sub(rain, 5, 9)) ? fmt(sum(sub(rain, 5, 9)), 0, " mm") : "n/a") + typ, "Wet monsoon months are cooler by day.") +
      row("Northeast monsoon (October to December)", (full(sub(rain, 9, 12)) ? fmt(sum(sub(rain, 9, 12)), 0, " mm") : "n/a") + typ, "Brings rain and cooler days, mainly to Tamil Nadu and the east coast.") +
      row("Day-night range", has(aMax) && has(aMin) ? fmt(aMax - aMin, 1, " °C") : "n/a", "A large range means clear, dry air. A small range means humid, cloudy weather.") +
      "</tbody></table></div>";

    const cell = (v, d, flag, rng) => {
    if (!has(v)) return "<td>n/a</td>";
    return `<td>${v.toFixed(d)}</td>`;

    };
    let b = `<p class="group">Month by month, ${year}</p><div class="chartwrap">${chartSvg(dRain, dMax, dMin, F.map((x) => !!(x.hi || x.rain)))}</div>` +
      '<p class="chartlegend"><span><i style="background:#6bb6e8"></i>Rainfall (mm)</span><span><i style="background:#e4572e"></i>Daily high (°C)</span><span><i style="background:#2a9d8f"></i>Daily low (°C)</span></p>';
    b += '<div class="table-wrap"><table><thead><tr><th>Month</th><th>Rain (mm)</th><th>High (°C)</th><th>Low (°C)</th><th>El Niño</th>' + (ov.indices.dmi ? "<th>IOD</th>" : "") + "</tr></thead><tbody>";
    MONTHS.forEach((m, k) => {
      b += `<tr><td>${m}</td>${cell(dRain[k], 1, F[k].rain, R[k].rain)}${cell(dMax[k], 1, F[k].hi, R[k].hi)}${cell(dMin[k], 1, F[k].lo, R[k].lo)}${cell(dOni[k], 2, F[k].oni, R[k].oni)}` +
           (ov.indices.dmi ? cell(dDmi[k], 2, F[k].dmi, R[k].dmi) : "") + "</tr>";
    });
    b += "</tbody></table></div>";
    if (anyF) b += '<p class="small">Italic values are not measured. High and low: forecast from our model. El Niño and IOD: forecast from our statistical model. Rain: the typical value of past years, not a forecast. Each has its likely range in brackets. Faded bars and hollow dots in the chart are the same values.</p>';

    box.innerHTML = `<h2 class="dn">${esc(f.name)}</h2><p class="sub2">${esc(f.state)} · ${year}${isFc ? " (forecast from our model)" : ""}</p><div class="dgrid"><div>${a}</div><div>${b}</div></div>`;
    showLive(key);
  }

  // ---- live temperature (Open-Meteo, free, no key) ----
  function showLive(key) {
    const v = $("live-v"), t = $("live-t");
    if (!v || key !== selected) return;
    const l = live[key];
    if (!l) { v.textContent = "loading…"; return; }
    v.textContent = l.failed ? "unavailable" : fmt(l.temp, 1, " °C");
    t.textContent = l.failed ? "could not reach the weather service" : `live, as of ${l.time} IST`;
  }
  async function loadLive(key) {
    const f = featByKey[key];
    try {
      const j = await get(`https://api.open-meteo.com/v1/forecast?latitude=${f.lat.toFixed(3)}&longitude=${f.lon.toFixed(3)}&current=temperature_2m&timezone=Asia%2FKolkata`);
      live[key] = { temp: j.current.temperature_2m, time: String(j.current.time).slice(11, 16) };
    } catch (e) {
      live[key] = { failed: true };
    }
    showLive(key);
  }

  // ---- El Niño chart (last 3 years) ----
  (function drawOni() {
    const s = ov.oni.series, W = 640, H = 170, pad = 30;
    const lo = -1, hi = Math.max(3, ...s.map((p) => p.oni));
    const x = (i) => pad + (i * (W - pad - 10)) / (s.length - 1);
    const y = (v) => H - pad - ((v - lo) / (hi - lo)) * (H - pad - 12);
    const pts = s.map((p, i) => `${x(i).toFixed(1)},${y(p.oni).toFixed(1)}`).join(" ");
    $("oni-chart").innerHTML =
      `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="El Niño index over the last 36 months">` +
      `<line x1="${pad}" x2="${W - 10}" y1="${y(0.5)}" y2="${y(0.5)}" stroke="#b23a1d" stroke-dasharray="4 3"/>` +
      `<text x="${pad + 4}" y="${y(0.5) - 5}" font-size="11" fill="#b23a1d">El Niño above +0.5</text>` +
      `<line x1="${pad}" x2="${W - 10}" y1="${y(0)}" y2="${y(0)}" stroke="#999"/>` +
      `<text x="4" y="${y(0) + 4}" font-size="11" fill="#555">0</text>` +
      `<polyline fill="none" stroke="#2b1a0e" stroke-width="2.5" points="${pts}"/>` +
      `<text x="${pad}" y="${H - 8}" font-size="11" fill="#555">${s[0].date}</text>` +
      `<text x="${W - 60}" y="${H - 8}" font-size="11" fill="#555">${s[s.length - 1].date}: ${ov.oni.latest > 0 ? "+" : ""}${ov.oni.latest}</text></svg>`;
  })();

  dsel.addEventListener("change", () => selectDistrict(dsel.value, false));
  $("year").addEventListener("change", renderDetail);
  setInterval(() => { if (selected) loadLive(selected); }, 10 * 60 * 1000);
  await renderDetail();
})(); } catch (e) { showFatal(e); throw e; }
})();