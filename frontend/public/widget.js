(function () {
  'use strict';

  if (window.__GIGACHADS_WIDGET__) return;
  window.__GIGACHADS_WIDGET__ = true;

  var params = new URLSearchParams(window.location.search);
  if (params.has('embed')) return;
  if (document.querySelector('.app[data-page], .app[data-embed], [data-embed="1"]')) return;

  try {
    if (
      window.parent &&
      window.parent !== window &&
      window.parent.document.querySelector('.app[data-page], .app[data-embed]')
    ) {
      return;
    }
  } catch (e) {
    /* another origin — that is the intended host page */
  }

  var scriptEl = document.currentScript;
  var ORIGIN = window.location.origin;
  try {
    if (scriptEl && scriptEl.src) ORIGIN = new URL(scriptEl.src).origin;
    else {
      var nodes = document.getElementsByTagName('script');
      for (var i = 0; i < nodes.length; i++) {
        var src = nodes[i].src || '';
        if (src.indexOf('/widget.js') !== -1) {
          ORIGIN = new URL(src).origin;
          break;
        }
      }
    }
  } catch (err) {
    ORIGIN = window.location.origin;
  }
  var ROOT_ID = 'gigachads-widget';
  var STYLE_ID = 'gigachads-widget-css';
  if (document.getElementById(ROOT_ID)) return;

  if (!document.getElementById(STYLE_ID)) {
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent =
      '#' + ROOT_ID + '{' +
        'position:fixed;z-index:2147483646;right:20px;bottom:20px;' +
        'font-family:Syne,"Plus Jakarta Sans",ui-sans-serif,system-ui,sans-serif;' +
        'line-height:1;box-sizing:border-box;' +
      '}' +
      '#' + ROOT_ID + ' *,#' + ROOT_ID + ' *::before,#' + ROOT_ID + ' *::after{box-sizing:border-box;}' +
      '#' + ROOT_ID + ' .gcw-btn{' +
        'display:inline-flex;align-items:center;justify-content:center;' +
        'width:56px;height:56px;padding:0;border:0;border-radius:50%;' +
        'background:#1856FF;color:#fff;cursor:pointer;' +
        'font-family:inherit;font-size:18px;font-weight:800;letter-spacing:0;' +
        'box-shadow:0 8px 28px rgba(24,86,255,.48),0 2px 8px rgba(0,0,0,.28);' +
        'transition:transform .18s ease,filter .18s ease;' +
      '}' +
      '#' + ROOT_ID + ' .gcw-btn:hover{filter:brightness(1.08);transform:translateY(-1px);}' +
      '#' + ROOT_ID + ' .gcw-btn:focus-visible{outline:2px solid #fff;outline-offset:3px;}' +
      '#' + ROOT_ID + ' .gcw-panel{' +
        'display:none;position:absolute;right:0;bottom:72px;' +
        'width:380px;height:560px;overflow:hidden;border:0;border-radius:16px;' +
        'background:#070c19;box-shadow:0 18px 48px rgba(0,0,0,.4);' +
      '}' +
      '#' + ROOT_ID + '.is-open .gcw-panel{display:block;}' +
      '#' + ROOT_ID + ' .gcw-panel iframe{' +
        'display:block;width:100%;height:100%;border:0;background:#070c19;' +
      '}' +
      '@media (max-width:420px){' +
        '#' + ROOT_ID + '{' +
          'right:12px;bottom:12px;' +
        '}' +
        '#' + ROOT_ID + ' .gcw-panel{' +
          'width:min(380px,calc(100vw - 24px));' +
          'height:min(560px,calc(100dvh - 96px));' +
        '}' +
      '}';
    (document.head || document.documentElement).appendChild(style);
  }

  var root = document.createElement('div');
  root.id = ROOT_ID;

  var panel = document.createElement('div');
  panel.className = 'gcw-panel';
  panel.hidden = true;

  var frame = document.createElement('iframe');
  frame.title = 'Чат GIGACHADS';
  frame.setAttribute('allow', 'clipboard-write');
  panel.appendChild(frame);

  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'gcw-btn';
  btn.textContent = 'G';
  btn.setAttribute('aria-label', 'Открыть чат GIGACHADS');
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', ROOT_ID + '-panel');
  panel.id = ROOT_ID + '-panel';

  var loaded = false;
  var open = false;

  function setOpen(next) {
    open = next;
    root.classList.toggle('is-open', open);
    panel.hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    btn.setAttribute('aria-label', open ? 'Закрыть чат GIGACHADS' : 'Открыть чат GIGACHADS');
    btn.textContent = open ? '×' : 'G';
    if (open && !loaded) {
      frame.src = ORIGIN + '/?embed=1';
      loaded = true;
    }
  }

  btn.addEventListener('click', function () {
    setOpen(!open);
  });

  root.appendChild(panel);
  root.appendChild(btn);

  function mount() {
    if (document.getElementById(ROOT_ID)) return;
    (document.body || document.documentElement).appendChild(root);
  }
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
