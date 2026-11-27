(function () {
  "use strict";
  // Signalbox dashboard tab (M9). Plain JS against the Hermes plugin SDK: no build step, no network access
  // other than this plugin's own /api/plugins/signalbox/ routes, no secret values (the API redacts).
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  var React = SDK.React;
  var h = React.createElement;
  var useState = React.useState;
  var useEffect = React.useEffect;
  var BASE = "/api/plugins/signalbox";

  function api(path, method, body) {
    if (body === undefined) return SDK.fetchJSON(BASE + path, method ? { method: method } : undefined);
    return SDK.fetchJSON(BASE + path, { method: method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }

  function useLoad(path, tick) {
    var s = useState({ loading: true, data: null, error: null });
    useEffect(function () {
      var live = true;
      api(path).then(function (d) { if (live) s[1]({ loading: false, data: d, error: null }); },
                      function (e) { if (live) s[1]({ loading: false, data: null, error: String(e && e.message || e) }); });
      return function () { live = false; };
    }, [path, tick]);
    return s[0];
  }

  function Status(props) {
    return h("p", { role: "status", "aria-live": "polite" }, props.text || "");
  }

  // --- Modules view (H5 WP3; #206, #208, #210) ---------------------------------------------------------------
  // Every value is explained (tooltips that open on hover and on keyboard focus, a legend under the table),
  // a button that cannot succeed is disabled with the reason and the command that fixes it, and a refused
  // action shows the core's message on its row. Module-written text is always rendered as text.
  var PROG = "hermes signalbox";
  var HTTPS = /^https:\/\/([A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?)(?::[0-9]{1,5})?(?:[\/?#][A-Za-z0-9._~:\/?#@!$&'()*+,;=%-]*)?$/;

  // A manifest link is third-party text: only a plain https URL is ever turned into a link.
  function safeUrl(url) {
    return typeof url === "string" && HTTPS.test(url) ? url : null;
  }

  function hostOf(url) {
    var m = typeof url === "string" ? HTTPS.exec(url) : null;
    return m ? m[1] : null;
  }

  function entry(table, key) {
    var e = table && table[key];
    return { label: (e && e.label) || String(key || ""), meaning: (e && e.meaning) || "" };
  }

  // What the Action cell of one row does, and why it may not.
  function rowModel(m, labels) {
    var active = m.status === "active";
    var missing = m.missing_grants || [];
    var caps = (labels && labels.capabilities) || {};
    var model = {
      id: m.id,
      action: active ? "deactivate" : "activate",
      actionLabel: (active ? "Stop " : "Start ") + m.id,
      reason: null,
      command: null,
    };
    if (active) return model;
    if (m.mode === "disabled") {
      model.reason = "This module is disabled. Change its start mode to start it.";
    } else if (missing.length) {
      model.reason = "Can't start yet. It needs " + missing.length + (missing.length === 1 ? " permission: " : " permissions: ") +
        missing.map(function (c) { return entry(caps, c).label; }).join(", ") + ". Grant them from a terminal:";
      model.command = PROG + " module grant " + m.id + " --capability " + missing[0];
    }
    return model;
  }

  // The links of one row: the git repository, the homepage, the documentation and the upstream projects.
  function sourceLinks(m) {
    var out = [];
    function add(url, text) {
      var safe = safeUrl(url);
      if (safe) out.push({ href: safe, text: String(text) + " (" + hostOf(safe) + ")" });
    }
    var source = m.source || {};
    if (source.kind === "git" && typeof source.url === "string") add(source.url.replace(/\.git$/, ""), "Repository");
    var links = m.links || {};
    add(links.homepage, "Homepage");
    add(links.docs, "Documentation");
    (m.based_on || []).forEach(function (b) {
      if (b && b.name) add(b.url, "Based on " + b.name);
    });
    return out;
  }

  function sourceText(m) {
    var source = m.source || {};
    if (source.kind === "bundled") return "Bundled with Signalbox";
    if (source.kind === "git") {
      return "Git, commit " + String(source.ref || "?").slice(0, 7) + " (channel " + String(source.channel || "main") + ")";
    }
    return "Unknown";
  }

  function healthText(m) {
    if (m.status !== "active") return "Not running";
    if (m.health === "ok") return "Healthy";
    return m.health ? String(m.health) : "No answer";
  }

  // A term with its meaning: shown on hover and on keyboard focus, closed with Esc (WCAG 2.2, 1.4.13).
  function Term(props) {
    var off = useState(false);
    var tip = "sy-tip-" + props.marker;
    return h("span", { className: "sy-term", tabIndex: 0, "aria-describedby": tip, "data-sy": props.marker,
      onKeyDown: function (e) { if (e && e.key === "Escape") off[1](true); },
      onBlur: function () { off[1](false); } },
      props.text,
      h("span", { role: "tooltip", id: tip, className: off[0] ? "sy-tip sy-tip-off" : "sy-tip" }, props.meaning));
  }

  function Legend(props) {
    var groups = [["Status", props.labels.statuses], ["Start mode", props.labels.modes]];
    return h("section", { className: "sy-legend", "aria-labelledby": "sy-legend-h", "data-sy": "legend" },
      h("h2", { id: "sy-legend-h" }, "What the columns mean"),
      groups.map(function (g) {
        return h("dl", { key: g[0] }, h("dt", { className: "sy-legend-group" }, g[0]),
          Object.keys(g[1] || {}).map(function (k) {
            return h("dd", { key: k }, h("strong", null, g[1][k].label), ": " + g[1][k].meaning);
          }));
      }),
      h("dl", null, h("dt", { className: "sy-legend-group" }, "Health"),
        h("dd", null, "What the module's own check reports while it runs.")),
      h("dl", null, h("dt", { className: "sy-legend-group" }, "Action"),
        h("dd", null, "Start or stop a module. Permissions are granted from a terminal or a Hermes chat, never here.")));
  }

  function Modules(props) {
    var st = useLoad("/modules", props.tick);
    var lb = useLoad("/labels", 0);
    var errors = useState({});
    if (st.loading) return h(Status, { text: "Loading modules" });
    if (st.error) return h(Status, { text: "Could not load modules: " + st.error });
    var labels = lb.data || {};

    function run(m, path, body) {
      api("/modules/" + encodeURIComponent(m.id) + path, "POST", body).then(function () {
        var next = Object.assign({}, errors[0]);
        delete next[m.id];
        errors[1](next);
        props.refresh();
      }, function (e) {
        // never discard a refusal: the core's message stays on the row until the next action
        var next = Object.assign({}, errors[0]);
        next[m.id] = String((e && e.message) || e);
        errors[1](next);
      });
    }

    var failed = Object.keys(errors[0]).length;
    return h("section", { "aria-labelledby": "sy-modules-h" },
      h("h2", { id: "sy-modules-h" }, "Modules"),
      h("p", { className: "sy-help" }, "What is installed, whether it is running, and what each module needs before it can start."),
      h("p", { role: "status", "aria-live": "polite", "data-sy": "live", className: "sy-live" },
        failed ? failed + (failed === 1 ? " action was refused. See its row." : " actions were refused. See their rows.") : ""),
      h("table", { className: "sy-table" },
        h("caption", { className: "sy-caption" }, "Installed modules"),
        h("thead", null, h("tr", null,
          ["Module", "State", "Start mode", "Health", "Version", "Source", "Update", "Action"].map(function (c) {
            return h("th", { scope: "col", key: c }, c);
          }))),
        h("tbody", null, (st.data || []).map(function (m) {
          var model = rowModel(m, labels);
          var status = entry(labels.statuses, m.status);
          var reasonId = "sy-reason-" + m.id;
          var error = errors[0][m.id];
          return h("tr", { key: m.id, "data-sy": "row-" + m.id },
            h("th", { scope: "row" }, h("span", { className: "sy-name" }, m.id),
              m.summary ? h("span", { className: "sy-desc" }, String(m.summary)) : null),
            h("td", null, h(Term, { marker: "state-" + m.id, text: String(m.state || status.label), meaning: status.meaning }),
              m.status === "failed" && m.error ? h("span", { className: "sy-desc" }, String(m.error)) : null),
            h("td", null, h("select", { "data-sy": "mode-" + m.id, "aria-label": "Start mode for " + m.id, value: m.mode || "manual",
              onChange: function (e) { run(m, "/mode", { mode: e.target.value }); } },
              ["auto", "manual", "disabled"].map(function (k) {
                var mode = entry(labels.modes, k);
                return h("option", { key: k, value: k, title: mode.meaning }, mode.label);
              }))),
            h("td", null, healthText(m)),
            h("td", null, String(m.version || "")),
            h("td", null, sourceText(m), sourceLinks(m).map(function (l, i) {
              return h("a", { key: i, className: "sy-link", href: l.href, rel: "noopener noreferrer", target: "_blank" }, l.text);
            })),
            h("td", null, String(m.update_text || "Unknown")),
            h("td", null,
              h("button", { type: "button", "data-sy": "action-" + m.id, className: "sy-button",
                "aria-disabled": model.reason ? "true" : "false", "aria-describedby": model.reason ? reasonId : null,
                onClick: function () { if (!model.reason) run(m, "/" + model.action); } }, model.actionLabel),
              model.reason ? h("span", { id: reasonId, className: "sy-reason", "data-sy": "reason-" + m.id }, model.reason,
                model.command ? h("code", null, " " + model.command) : null) : null,
              error ? h("p", { role: "alert", className: "sy-error", "data-sy": "error-" + m.id }, "Refused: " + error) : null));
        }))),
      h(Legend, { labels: labels }));
  }

  window.__SIGNALBOX_VIEW__ = { safeUrl: safeUrl, hostOf: hostOf, rowModel: rowModel, sourceLinks: sourceLinks, Modules: Modules };

  // --- Inbox view -----------------------------------------------------------------------------------------
  function Inbox(props) {
    var st = useLoad("/inbox", props.tick);
    if (st.loading) return h(Status, { text: "Loading inbox" });
    if (st.error) return h(Status, { text: "Inbox unavailable: " + st.error });
    var items = (st.data && st.data.items) || [];
    return h("section", { "aria-labelledby": "sy-inbox-h" },
      h("h2", { id: "sy-inbox-h" }, "Inbox (" + items.length + " open)"),
      items.length ? h("button", { type: "button", onClick: function () { api("/inbox/ack_all", "POST").then(props.refresh, props.refresh); } }, "Acknowledge all") : null,
      h("ul", null, items.map(function (it) {
        return h("li", { key: it.id, className: "sy-sev-" + it.severity },
          h("span", null, "[" + it.severity + "] " + (it.title || it.type) + " (" + it.module + ") " + (it.detail || "") + " "),
          h("button", { type: "button", onClick: function () { api("/inbox/" + encodeURIComponent(it.id) + "/ack", "POST").then(props.refresh, props.refresh); } }, "Acknowledge"));
      })));
  }

  function Report(props) {
    var kind = useState("health");
    var st = useLoad("/report/" + kind[0], props.tick);
    return h("section", { "aria-labelledby": "sy-report-h" },
      h("h2", { id: "sy-report-h" }, "Reports"),
      h("label", null, "Report ",
        h("select", { value: kind[0], onChange: function (e) { kind[1](e.target.value); } },
          ["health", "usage", "security", "changes"].map(function (k) { return h("option", { key: k, value: k }, k); }))),
      st.loading ? h(Status, { text: "Loading report" }) :
        st.error ? h(Status, { text: "Report unavailable: " + st.error }) :
          h("pre", { className: "sy-pre", tabIndex: 0 }, JSON.stringify(st.data, null, 2)));
  }

  var VIEWS = [["modules", "Modules", Modules], ["inbox", "Inbox", Inbox], ["reports", "Reports", Report]];

  function Page() {
    var view = useState("modules");
    var tick = useState(0);
    function refresh() { tick[1](tick[0] + 1); }
    var current = VIEWS.filter(function (v) { return v[0] === view[0]; })[0];
    return h("main", { className: "sy-root" },
      h("h1", null, "Signalbox"),
      h("div", { role: "tablist", "aria-label": "Signalbox views", className: "sy-tabs" },
        VIEWS.map(function (v) {
          return h("button", { type: "button", role: "tab", key: v[0], id: "sy-tab-" + v[0],
            "aria-selected": view[0] === v[0] ? "true" : "false", "aria-controls": "sy-panel",
            onClick: function () { view[1](v[0]); } }, v[1]);
        }),
        h("button", { type: "button", onClick: refresh }, "Refresh")),
      h("div", { role: "tabpanel", id: "sy-panel", "aria-labelledby": "sy-tab-" + view[0] },
        h(current[2], { tick: tick[0], refresh: refresh })));
  }

  window.__HERMES_PLUGINS__.register("signalbox", Page);
})();
