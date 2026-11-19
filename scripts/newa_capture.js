/* NEWA daily station capture, run inside https://newa.cornell.edu/ by the nightly browser session.

   NEWA's home page loads one station's data when that station is picked. This recorder watches only
   those page loads (it makes no requests of its own) and keeps a compact summary per station:
     observed  - daily rain (in) and high/low (F) for the last 10 days, from the page's daily data
     forecast  - per day for the next 6 days: high/low and weather word (daily forecast), the highest
                 12-hour chance of rain (%), and the rain amount (in) summed over hours that have one,
                 with how many of the 24 hours had an amount (24 = complete day)
   Usage in the page:  1) evaluate this file once (installs the recorder)
                       2) pick each station in the "Weather Stations" box
                       3) evaluate  JSON.stringify(window.__newaSummary())
*/
(function () {
  if (window.__newaInstalled) return 'already installed';
  window.__newaInstalled = true; window.__newa = {};
  const num = v => { const x = parseFloat(v); return isNaN(x) ? null : x; };
  function summarise(sid, j) {
    const out = { sid, captured_at: new Date().toISOString(), observed: [], forecast: {} };
    const df = j.dlyFields || [], dd = j.dlyData || [];
    const iD = df.indexOf('date'), iP = df.indexOf('prcp'), iX = df.indexOf('maxt'), iN = df.indexOf('mint');
    for (const r of dd.slice(-10)) out.observed.push({ date: String(r[iD]).slice(0, 10), rain_in: num(r[iP]), high_f: num(r[iX]), low_f: num(r[iN]) });
    const hf = j.hrlyFields || [], hd = j.hrlyData || [];
    if (hd.length) out.last_observation = hd[hd.length - 1][hf.indexOf('date')];
    const ff = j.fcstFields || [], fd = j.fcstData || [];
    const fD = ff.indexOf('date'), fP = ff.indexOf('pop12'), fQ = ff.indexOf('qpf'), fT = ff.indexOf('temp');
    for (const r of fd) {
      const day = String(r[fD]).slice(0, 10), f = out.forecast[day] || (out.forecast[day] = { rain_in: 0, rain_hours: 0, max_pop12: null, hours: 0 });
      f.hours += 1;
      const q = num(r[fQ]); if (q !== null) { f.rain_in = Math.round((f.rain_in + q) * 1000) / 1000; f.rain_hours += 1; }
      const p = num(r[fP]); if (p !== null) f.max_pop12 = Math.max(f.max_pop12 ?? 0, p);
    }
    const xf = j.dlyFcstFields || [], xd = j.dlyFcstData || [];
    for (const r of xd) {
      const day = String(r[xf.indexOf('date')]).slice(0, 10), f = out.forecast[day] || (out.forecast[day] = { rain_in: 0, rain_hours: 0, max_pop12: null, hours: 0 });
      f.high_f = num(r[xf.indexOf('maxt')]); f.low_f = num(r[xf.indexOf('mint')]); f.weather = r[xf.indexOf('weather')];
    }
    return out;
  }
  const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u) { this.__newaUrl = String(u); return open.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    if (this.__newaUrl && this.__newaUrl.includes('stnHrly')) {
      this.addEventListener('load', () => {
        try { const sid = JSON.parse(body).sid; window.__newa[sid] = summarise(sid, JSON.parse(this.responseText)); }
        catch (e) { window.__newa['error-' + Date.now()] = { error: String(e) }; }
      });
    }
    return send.apply(this, arguments);
  };
  window.__newaSummary = () => ({ source: 'https://newa.cornell.edu/ station pages (NRCC data loaded by the page)', stations: window.__newa });
  return 'installed';
})();
