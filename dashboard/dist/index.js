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

  function api(path, method) {
    return SDK.fetchJSON(BASE + path, method ? { method: method } : undefined);
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

  function Modules(props) {
    var st = useLoad("/modules", props.tick);
    if (st.loading) return h(Status, { text: "Loading modules" });
    if (st.error) return h(Status, { text: "Could not load modules: " + st.error });
    return h("table", { className: "sy-table" },
      h("caption", null, "Modules"),
      h("thead", null, h("tr", null,
        ["Module", "Status", "Mode", "Health", "Action"].map(function (c) { return h("th", { scope: "col", key: c }, c); }))),
      h("tbody", null, (st.data || []).map(function (m) {
        var active = m.status === "active";
        return h("tr", { key: m.id },
          h("th", { scope: "row" }, m.id),
          h("td", null, m.status),
          h("td", null, m.mode || ""),
          h("td", null, m.health || ""),
          h("td", null, h("button", { type: "button", onClick: function () {
            api("/modules/" + encodeURIComponent(m.id) + "/" + (active ? "deactivate" : "activate"), "POST").then(props.refresh, props.refresh);
          } }, (active ? "Deactivate " : "Activate ") + m.id)));
      })));
  }

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
