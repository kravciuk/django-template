/*!
 * VilniusWeatherWidget — лёгкий виджет погоды (Lithuania/Vilnius) на 1 / 3 / 7 дней.
 * Без зависимостей. Данные: Open-Meteo (open-meteo.com), API-ключ не требуется.
 *
 * Использование:
 *   <div id="weather"></div>
 *   <script src="weather-widget.js"></script>
 *   <script>WeatherWidget.init({ el: '#weather' });</script>
 *
 * Опции:
 *   el        — селектор или DOM-элемент (обязательно)
 *   latitude  — 54.6872   (по умолчанию Вильнюс)
 *   longitude — 25.2797
 *   timezone  — 'Europe/Vilnius'
 *   city      — 'Вильнюс'
 *   days      — стартовый диапазон: 1 | 3 | 7 (по умолчанию 3)
 *   lang      — 'ru' | 'lt' | 'en'
 *   units     — 'metric' | 'imperial'
 *   theme     — 'light' | 'dark' | 'auto'
 *   refresh   — автообновление в минутах (0 = выкл, по умолчанию 30)
 */
(function (global) {
  'use strict';

  var API = 'https://api.open-meteo.com/v1/forecast';

  var I18N = {
    ru: {
      today: 'Сегодня', day1: '1 день', day3: '3 дня', day7: '7 дней',
      feels: 'Ощущается', wind: 'Ветер', hum: 'Влажность', precip: 'Осадки',
      sunrise: 'Восход', sunset: 'Закат', updated: 'Обновлено',
      loading: 'Загрузка погоды…', error: 'Не удалось загрузить погоду',
      retry: 'Повторить',
      days: ['Вс','Пн','Вт','Ср','Чт','Пт','Сб'],
      wmo: {0:'Ясно',1:'Преим. ясно',2:'Переменная облачность',3:'Пасмурно',45:'Туман',48:'Изморозь',
        51:'Морось слабая',53:'Морось',55:'Морось сильная',56:'Ледяная морось',57:'Ледяная морось',
        61:'Дождь слабый',63:'Дождь',65:'Дождь сильный',66:'Ледяной дождь',67:'Ледяной дождь',
        71:'Снег слабый',73:'Снег',75:'Снег сильный',77:'Снежные зёрна',
        80:'Ливень слабый',81:'Ливень',82:'Ливень сильный',85:'Снегопад',86:'Сильный снегопад',
        95:'Гроза',96:'Гроза с градом',99:'Гроза с градом'}
    },
    lt: {
      today: 'Šiandien', day1: '1 diena', day3: '3 dienos', day7: '7 dienos',
      feels: 'Jaučiasi', wind: 'Vėjas', hum: 'Drėgmė', precip: 'Krituliai',
      sunrise: 'Saulėtekis', sunset: 'Saulėlydis', updated: 'Atnaujinta',
      loading: 'Kraunama…', error: 'Nepavyko įkelti orų', retry: 'Bandyti dar kartą',
      days: ['Sk','Pr','An','Tr','Kt','Pn','Št'],
      wmo: {0:'Giedra',1:'Beveik giedra',2:'Debesuota su pragiedruliais',3:'Debesuota',45:'Rūkas',48:'Šerkšnas',
        51:'Silpna dulksna',53:'Dulksna',55:'Stipri dulksna',56:'Ledinė dulksna',57:'Ledinė dulksna',
        61:'Silpnas lietus',63:'Lietus',65:'Smarkus lietus',66:'Ledinis lietus',67:'Ledinis lietus',
        71:'Silpnas sniegas',73:'Sniegas',75:'Smarkus sniegas',77:'Sniego kruopos',
        80:'Trumpas lietus',81:'Liūtis',82:'Smarki liūtis',85:'Sniego krituliai',86:'Gausus sniegas',
        95:'Perkūnija',96:'Perkūnija su kruša',99:'Perkūnija su kruša'}
    },
    en: {
      today: 'Today', day1: '1 day', day3: '3 days', day7: '7 days',
      feels: 'Feels like', wind: 'Wind', hum: 'Humidity', precip: 'Precip.',
      sunrise: 'Sunrise', sunset: 'Sunset', updated: 'Updated',
      loading: 'Loading weather…', error: 'Failed to load weather', retry: 'Retry',
      days: ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'],
      wmo: {0:'Clear',1:'Mostly clear',2:'Partly cloudy',3:'Overcast',45:'Fog',48:'Rime fog',
        51:'Light drizzle',53:'Drizzle',55:'Heavy drizzle',56:'Freezing drizzle',57:'Freezing drizzle',
        61:'Light rain',63:'Rain',65:'Heavy rain',66:'Freezing rain',67:'Freezing rain',
        71:'Light snow',73:'Snow',75:'Heavy snow',77:'Snow grains',
        80:'Light showers',81:'Showers',82:'Heavy showers',85:'Snow showers',86:'Heavy snow showers',
        95:'Thunderstorm',96:'Thunderstorm w/ hail',99:'Thunderstorm w/ hail'}
    }
  };

  // SVG-иконки (без внешних картинок)
  function icon(code, isDay) {
    var sun = '<circle cx="24" cy="24" r="9" fill="#FDB813"/><g stroke="#FDB813" stroke-width="3" stroke-linecap="round">' +
      '<path d="M24 4v6M24 38v6M4 24h6M38 24h6M10 10l4 4M34 34l4 4M38 10l-4 4M14 34l-4 4"/></g>';
    var moon = '<path d="M30 6a18 18 0 1 0 12 30A20 20 0 0 1 30 6z" fill="#C9D6E8"/>';
    var cloud = '<path d="M16 38h20a9 9 0 0 0 .6-18A13 13 0 0 0 12 24a7 7 0 0 0 4 14z" fill="#B9C6D6"/>';
    var cloudW = '<path d="M16 36h20a9 9 0 0 0 .6-18A13 13 0 0 0 12 22a7 7 0 0 0 4 14z" fill="#9FB0C4"/>';
    var rain = '<g stroke="#4A90D9" stroke-width="3" stroke-linecap="round"><path d="M18 40l-2 5M26 40l-2 5M34 40l-2 5"/></g>';
    var snow = '<g fill="#7FB5E8"><circle cx="17" cy="43" r="2.5"/><circle cx="25" cy="43" r="2.5"/><circle cx="33" cy="43" r="2.5"/></g>';
    var bolt = '<path d="M26 38l-8 8h6l-2 8 10-11h-6l4-5z" fill="#F5A623"/>';
    var fog = '<g stroke="#B9C6D6" stroke-width="3.5" stroke-linecap="round"><path d="M10 30h28M8 37h32M12 44h24"/></g>';
    var body;
    if (code === 0) body = isDay ? sun : moon;
    else if (code === 1 || code === 2) body = (isDay ? '<g transform="translate(-4,-4) scale(.8)">'+sun+'</g>' : '<g transform="translate(-2,-4) scale(.8)">'+moon+'</g>') + cloud;
    else if (code === 3) body = cloudW;
    else if (code === 45 || code === 48) body = fog;
    else if (code >= 71 && code <= 77 || code === 85 || code === 86) body = cloudW + snow;
    else if (code >= 95) body = cloudW + bolt;
    else body = cloudW + rain;
    return '<svg class="ww-ic" viewBox="0 0 48 52" aria-hidden="true">' + body + '</svg>';
  }

  var CSS = [
    '.ww{--bg:#fff;--fg:#16202c;--mut:#6b7b8d;--line:#e6ecf2;--acc:#2f6fd0;--card:#f6f9fc;',
    'font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;background:var(--bg);color:var(--fg);',
    'border:1px solid var(--line);border-radius:16px;padding:16px;max-width:640px;box-sizing:border-box;',
    'box-shadow:0 6px 22px rgba(20,40,70,.07)}',
    '.ww *{box-sizing:border-box}',
    '.ww--dark{--bg:#131a24;--fg:#eaf1f8;--mut:#93a4b7;--line:#25303e;--acc:#6aa6ff;--card:#1b2431;box-shadow:none}',
    '.ww-head{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:12px}',
    '.ww-city{font-size:16px;font-weight:650;margin:0}',
    '.ww-sub{font-size:12px;color:var(--mut)}',
    '.ww-tabs{display:inline-flex;background:var(--card);border:1px solid var(--line);border-radius:999px;padding:3px;gap:2px}',
    '.ww-tab{border:0;background:transparent;color:var(--mut);font:inherit;font-size:13px;padding:6px 13px;border-radius:999px;cursor:pointer}',
    '.ww-tab:hover{color:var(--fg)}',
    '.ww-tab[aria-selected="true"]{background:var(--acc);color:#fff}',
    '.ww-now{display:flex;align-items:center;gap:14px;background:var(--card);border-radius:14px;padding:14px;margin-bottom:12px}',
    '.ww-now .ww-ic{width:64px;height:68px;flex:0 0 auto}',
    '.ww-temp{font-size:38px;font-weight:700;line-height:1}',
    '.ww-desc{font-size:14px;margin-top:4px}',
    '.ww-meta{margin-left:auto;text-align:right;font-size:12.5px;color:var(--mut);line-height:1.7;white-space:nowrap}',
    '.ww-list{display:grid;gap:6px}',
    '.ww-row{display:grid;grid-template-columns:74px 42px 1fr auto;align-items:center;gap:10px;',
    'padding:8px 10px;border-radius:10px;background:var(--card)}',
    '.ww-row .ww-ic{width:34px;height:37px}',
    '.ww-dname{font-size:13px;font-weight:600}',
    '.ww-ddate{font-size:11px;color:var(--mut)}',
    '.ww-dtext{font-size:13px;color:var(--mut);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.ww-t{font-size:14px;font-variant-numeric:tabular-nums}',
    '.ww-t b{font-weight:700}.ww-t span{color:var(--mut)}',
    '.ww-foot{margin-top:10px;font-size:11px;color:var(--mut);display:flex;justify-content:space-between;gap:8px}',
    '.ww-foot a{color:inherit}',
    '.ww-err{padding:18px;text-align:center;font-size:14px}',
    '.ww-btn{margin-top:8px;border:1px solid var(--line);background:var(--card);color:var(--fg);font:inherit;',
    'padding:6px 14px;border-radius:8px;cursor:pointer}',
    '.ww-skel{height:14px;border-radius:6px;background:linear-gradient(90deg,var(--card),var(--line),var(--card));',
    'background-size:200% 100%;animation:ww-sh 1.2s infinite}',
    '@keyframes ww-sh{0%{background-position:200% 0}100%{background-position:-200% 0}}',
    '@media(max-width:420px){.ww-row{grid-template-columns:64px 34px 1fr auto;gap:8px}.ww-dtext{display:none}',
    '.ww-meta{margin-left:0;width:100%;text-align:left;white-space:normal}.ww-now{flex-wrap:wrap}}'
  ].join('');

  function injectCSS() {
    if (document.getElementById('ww-style')) return;
    var s = document.createElement('style');
    s.id = 'ww-style'; s.textContent = CSS;
    document.head.appendChild(s);
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function Widget(opts) {
    this.o = Object.assign({
      latitude: 54.6872, longitude: 25.2797, timezone: 'Europe/Vilnius',
      city: null, days: 3, lang: 'ru', units: 'metric', theme: 'light', refresh: 30
    }, opts || {});
    this.t = I18N[this.o.lang] || I18N.ru;
    if (!this.o.city) this.o.city = { ru: 'Вильнюс, Литва', lt: 'Vilnius, Lietuva', en: 'Vilnius, Lithuania' }[this.o.lang] || 'Vilnius';
    this.range = [1, 3, 7].indexOf(this.o.days) > -1 ? this.o.days : 3;

    this.el = typeof this.o.el === 'string' ? document.querySelector(this.o.el) : this.o.el;
    if (!this.el) throw new Error('WeatherWidget: контейнер не найден');

    injectCSS();
    this.root = document.createElement('div');
    this.root.className = 'ww' + (this.isDark() ? ' ww--dark' : '');
    this.el.appendChild(this.root);

    this.renderLoading();
    this.load();
    if (this.o.refresh > 0) this.timer = setInterval(this.load.bind(this), this.o.refresh * 60000);
  }

  Widget.prototype.isDark = function () {
    return this.o.theme === 'dark' || (this.o.theme === 'auto' &&
      global.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
  };

  Widget.prototype.units = function () {
    return this.o.units === 'imperial'
      ? { t: '°F', w: 'mph', p: 'in', tu: 'fahrenheit', wu: 'mph', pu: 'inch' }
      : { t: '°C', w: 'м/с', p: 'мм', tu: 'celsius', wu: 'ms', pu: 'mm' };
  };

  Widget.prototype.renderLoading = function () {
    var sk = '';
    for (var i = 0; i < 3; i++) sk += '<div class="ww-skel" style="margin:8px 0;height:44px"></div>';
    this.root.innerHTML = '<div class="ww-head"><div><p class="ww-city">' + esc(this.o.city) +
      '</p><div class="ww-sub">' + this.t.loading + '</div></div></div>' + sk;
  };

  Widget.prototype.renderError = function () {
    var self = this;
    this.root.innerHTML = '<div class="ww-err">' + this.t.error +
      '<br><button class="ww-btn" type="button">' + this.t.retry + '</button></div>';
    this.root.querySelector('.ww-btn').onclick = function () { self.renderLoading(); self.load(); };
  };

  Widget.prototype.load = function () {
    var self = this, u = this.units();
    var url = API + '?latitude=' + this.o.latitude + '&longitude=' + this.o.longitude +
      '&timezone=' + encodeURIComponent(this.o.timezone) +
      '&current=temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day' +
      '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,' +
      'wind_speed_10m_max,sunrise,sunset&forecast_days=7' +
      '&temperature_unit=' + u.tu + '&wind_speed_unit=' + u.wu + '&precipitation_unit=' + u.pu;

    fetch(url)
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { self.data = d; self.render(); })
      .catch(function (e) { console.error('[WeatherWidget]', e); self.renderError(); });
  };

  Widget.prototype.render = function () {
    var self = this, d = this.data, t = this.t, u = this.units();
    var c = d.current, dd = d.daily, r = Math.round;

    var tabs = [1, 3, 7].map(function (n) {
      return '<button class="ww-tab" type="button" role="tab" data-d="' + n + '" aria-selected="' +
        (self.range === n) + '">' + t['day' + n] + '</button>';
    }).join('');

    var head = '<div class="ww-head"><div><p class="ww-city">' + esc(this.o.city) + '</p>' +
      '<div class="ww-sub">' + t.updated + ': ' + new Date().toLocaleTimeString(this.o.lang, { hour: '2-digit', minute: '2-digit' }) + '</div></div>' +
      '<div class="ww-tabs" role="tablist">' + tabs + '</div></div>';

    var now = '<div class="ww-now">' + icon(c.weather_code, c.is_day === 1) +
      '<div><div class="ww-temp">' + r(c.temperature_2m) + u.t + '</div>' +
      '<div class="ww-desc">' + (t.wmo[c.weather_code] || '—') + '</div></div>' +
      '<div class="ww-meta">' + t.feels + ': ' + r(c.apparent_temperature) + u.t + '<br>' +
      t.wind + ': ' + r(c.wind_speed_10m) + ' ' + u.w + ' · ' + t.hum + ': ' + c.relative_humidity_2m + '%<br>' +
      t.sunrise + ' ' + dd.sunrise[0].slice(11) + ' · ' + t.sunset + ' ' + dd.sunset[0].slice(11) +
      '</div></div>';

    var rows = '';
    for (var i = 0; i < this.range; i++) {
      var dt = new Date(dd.time[i] + 'T12:00:00');
      var name = i === 0 ? t.today : t.days[dt.getDay()];
      var pp = dd.precipitation_probability_max[i];
      var extra = (pp != null && pp > 0 ? ' · ' + t.precip + ' ' + pp + '%' : '');
      rows += '<div class="ww-row"><div><div class="ww-dname">' + name + '</div>' +
        '<div class="ww-ddate">' + dt.getDate() + '.' + ('0' + (dt.getMonth() + 1)).slice(-2) + '</div></div>' +
        icon(dd.weather_code[i], true) +
        '<div class="ww-dtext">' + (t.wmo[dd.weather_code[i]] || '—') + extra + '</div>' +
        '<div class="ww-t"><b>' + r(dd.temperature_2m_max[i]) + u.t + '</b> <span>/ ' +
        r(dd.temperature_2m_min[i]) + u.t + '</span></div></div>';
    }

    this.root.innerHTML = head + (this.range === 1 ? now : now) + '<div class="ww-list">' + rows + '</div>' +
      '<div class="ww-foot"><span>Open-Meteo</span><span>' + this.o.timezone + '</span></div>';

    Array.prototype.forEach.call(this.root.querySelectorAll('.ww-tab'), function (b) {
      b.onclick = function () { self.range = +b.dataset.d; self.render(); };
    });
  };

  Widget.prototype.destroy = function () {
    clearInterval(this.timer);
    if (this.root && this.root.parentNode) this.root.parentNode.removeChild(this.root);
  };

  var WeatherWidget = {
    init: function (o) { return new Widget(o); },
    Widget: Widget
  };

  if (typeof module === 'object' && module.exports) module.exports = WeatherWidget;
  global.WeatherWidget = WeatherWidget;

  // Авто-инициализация для <div data-weather-widget ...>
  document.addEventListener('DOMContentLoaded', function () {
    Array.prototype.forEach.call(document.querySelectorAll('[data-weather-widget]'), function (el) {
      var o = { el: el };
      ['lang', 'theme', 'units', 'city', 'timezone'].forEach(function (k) { if (el.dataset[k]) o[k] = el.dataset[k]; });
      ['latitude', 'longitude', 'days', 'refresh'].forEach(function (k) { if (el.dataset[k]) o[k] = +el.dataset[k]; });
      new Widget(o);
    });
  });
})(typeof window !== 'undefined' ? window : this);
