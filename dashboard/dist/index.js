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

  // One GET per (path, tick). The last good answer stays on screen while the next one loads, so Refresh
  // does not blank the view. `at` is when the shown answer arrived; `settled` is called when a load ends.
  function useLoad(path, tick, settled) {
    var s = useState({ loading: true, data: null, error: null, at: null, path: path });
    useEffect(function () {
      var live = true;
      s[1](function (was) {
        return { loading: true, data: was.path === path ? was.data : null, error: null, at: was.at, path: path };
      });
      function done(data, error) {
        if (!live) return;
        s[1]({ loading: false, data: data, error: error, at: Date.now(), path: path });
        if (settled) settled();
      }
      api(path).then(function (d) { done(d, null); }, function (e) { done(null, String(e && e.message || e)); });
      return function () { live = false; };
    }, [path, tick]);
    if (s[0].path && s[0].path !== path) return { loading: true, data: null, error: null, at: null };
    return s[0];
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function toMillis(value) {
    if (typeof value === "number") return isFinite(value) && value > 0 ? (value < 1e11 ? value * 1000 : value) : NaN;
    if (typeof value !== "string" || !value) return NaN;
    return Date.parse(value.replace(/(\.\d{3})\d+/, "$1"));
  }

  // A stored time (ISO text, seconds or milliseconds) in this computer's time zone, with how long ago it was.
  function formatWhen(value, now) {
    var ms = toMillis(value);
    if (isNaN(ms)) return typeof value === "string" ? value : "";
    var d = new Date(ms);
    var stamp = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
    var ago = Math.floor(((now === undefined ? Date.now() : now) - ms) / 1000);
    if (ago < -60) return stamp;
    var rel = ago < 60 ? "just now" : ago < 3600 ? Math.floor(ago / 60) + " min ago" :
      ago < 172800 ? Math.floor(ago / 3600) + " h ago" : Math.floor(ago / 86400) + " d ago";
    return stamp + " (" + rel + ")";
  }

  function times(n) { return n > 1 ? n + " times" : "Once"; }

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
      actionLabel: active ? "Stop" : "Start",
      actionName: (active ? "Stop " : "Start ") + m.id,
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
    if (source.kind === "bundled") return "Bundled and updated with Signalbox";
    if (source.kind === "git") {
      return "Installed from git, commit " + String(source.ref || "?").slice(0, 7) + " (channel " + String(source.channel || "main") + ")";
    }
    return "Unknown";
  }

  // State answers one question: is it running? The start mode has its own column.
  function stateText(m) {
    if (m.status === "failed") return "Error";
    if (m.status === "active") return "Running";
    if ((m.missing_grants || []).length && m.mode !== "disabled") return "Needs permissions";
    return "Not running";
  }

  // Only a running module that does not report "ok" has something to say about its health.
  function healthIssue(m) {
    if (m.status !== "active" || m.health === "ok") return null;
    return m.health ? String(m.health) : "No answer";
  }

  // What differs from the ordinary case stays visible beside the name; everything else is in About.
  function tagsOf(m) {
    var out = [];
    var kind = (m.source || {}).kind;
    var update = (m.update || {}).state;
    if (kind === "git") out.push(["tag-git-" + m.id, "From git"]);
    else if (kind !== "bundled") out.push(["tag-source-" + m.id, "Unknown source"]);
    if (update === "available") out.push(["tag-update-" + m.id, "Update available"]);
    if (update === "check_failed") out.push(["tag-update-" + m.id, "Update check failed"]);
    return out;
  }

  function aboutLines(m, labels) {
    var caps = (labels && labels.capabilities) || {};
    function names(list) { return list.map(function (c) { return entry(caps, c).label; }).join(", "); }
    var granted = m.granted || [];
    var rest = (m.requested || []).filter(function (c) { return granted.indexOf(c) < 0; });
    var lines = [["Source", sourceText(m)]];
    if ((m.source || {}).kind !== "bundled") lines.push(["Update", String(m.update_text || "Unknown")]);
    lines.push(["Runs", m.isolation === "in-process" ? "inside the Signalbox process" : "in its own process"]);
    lines.push(["Permissions granted", granted.length ? names(granted) : "none"]);
    if (rest.length) lines.push(["Not granted", names(rest)]);
    if (m.license) lines.push(["License", String(m.license)]);
    return lines;
  }

  // One control beside the module's name: where it comes from, how it updates, what it may do, its links.
  // It opens on hover, on keyboard focus and on click or tap; Esc closes it (WCAG 2.2, 1.4.13).
  function About(props) {
    var m = props.m;
    var mode = useState("auto"); // "auto": hover and focus decide; "open": pinned by a click; "off": closed by Esc
    var id = "sy-about-" + m.id;
    function rest() { if (mode[0] === "off") mode[1]("auto"); }
    return h("span", { className: "sy-about", "data-sy": "about-wrap-" + m.id, onBlur: rest, onMouseLeave: rest,
      onKeyDown: function (e) { if (e && e.key === "Escape") mode[1]("off"); } },
      h("button", { type: "button", className: "sy-about-button", "data-sy": "about-" + m.id, "aria-label": "About " + m.id,
        "aria-expanded": mode[0] === "open" ? "true" : "false", "aria-controls": id,
        onClick: function () { mode[1](mode[0] === "open" ? "off" : "open"); } }, "\u24D8"),
      h("span", { id: id, className: "sy-about-panel" + (mode[0] === "auto" ? "" : " sy-about-" + mode[0]), "data-sy": "about-panel-" + m.id },
        aboutLines(m, props.labels).map(function (line) {
          return h("span", { key: line[0], className: "sy-about-line" }, h("strong", null, line[0] + ": "), line[1]);
        }),
        sourceLinks(m).map(function (l, i) {
          return h("a", { key: i, className: "sy-link", href: l.href, rel: "noopener noreferrer", target: "_blank" }, l.text);
        })));
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
    return h("details", { className: "sy-legend", "data-sy": "legend" },
      h("summary", null, "What the columns mean"),
      groups.map(function (g) {
        return h("dl", { key: g[0] }, h("dt", { className: "sy-legend-group" }, g[0]),
          Object.keys(g[1] || {}).map(function (k) {
            return h("dd", { key: k }, h("strong", null, g[1][k].label), ": " + g[1][k].meaning);
          }));
      }),
      h("dl", null, h("dt", { className: "sy-legend-group" }, "Health"),
        h("dd", null, "A running module whose own check reports a problem shows it under its state.")),
      h("dl", null, h("dt", { className: "sy-legend-group" }, "About (\u24D8)"),
        h("dd", null, "Beside each name: where the module comes from, how it updates, its permissions, licence and links. " +
          "Point at it, move to it with Tab, or click it; Esc closes it.")),
      h("dl", null, h("dt", { className: "sy-legend-group" }, "Action"),
        h("dd", null, "Start or stop a module. Permissions are granted from a terminal or a Hermes chat, never here.")));
  }

  function Modules(props) {
    var st = useLoad("/modules", props.tick, props.settled);
    var lb = useLoad("/labels", 0);
    var errors = useState({});
    if (st.loading && !st.data) return h(Status, { text: "Loading modules" });
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
    var rows = st.data || [];
    function count(test) { return rows.filter(test).length; }
    var summary = count(function (m) { return m.status === "active"; }) + " of " + rows.length + " modules running \u00B7 " +
      count(function (m) { return m.status === "failed"; }) + " failed \u00B7 " +
      count(function (m) { return stateText(m) === "Needs permissions"; }) + " waiting for permissions";
    return h("section", { "aria-labelledby": "sy-modules-h" },
      h("h2", { id: "sy-modules-h" }, "Modules"),
      h("p", { className: "sy-help" }, "What is installed, whether it is running, and what each module needs before it can start."),
      h("p", { className: "sy-summary", "data-sy": "summary" }, summary),
      h("p", { role: "status", "aria-live": "polite", "data-sy": "live", className: "sy-live" },
        failed ? failed + (failed === 1 ? " action was refused. See its row." : " actions were refused. See their rows.") : ""),
      h("table", { className: "sy-table" },
        h("caption", { className: "sy-caption" }, "Installed modules"),
        h("thead", null, h("tr", null,
          ["Module", "State", "Start mode", "Version", "Action"].map(function (c) {
            return h("th", { scope: "col", key: c }, c);
          }))),
        h("tbody", null, rows.map(function (m) {
          var model = rowModel(m, labels);
          var status = entry(labels.statuses, m.status);
          var reasonId = "sy-reason-" + m.id;
          var error = errors[0][m.id];
          var issue = healthIssue(m);
          return h("tr", { key: m.id, "data-sy": "row-" + m.id },
            h("th", { scope: "row" },
              h("span", { className: "sy-namerow" }, h("span", { className: "sy-name" }, m.id), h(About, { m: m, labels: labels }),
                tagsOf(m).map(function (t) { return h("span", { key: t[0], className: "sy-badge sy-tag", "data-sy": t[0] }, t[1]); })),
              m.summary ? h("span", { className: "sy-desc" }, String(m.summary)) : null),
            h("td", null, h(Term, { marker: "state-" + m.id, text: stateText(m), meaning: status.meaning }),
              issue ? h("span", { className: "sy-desc", "data-sy": "health-" + m.id }, "Health: " + issue) : null,
              m.status === "failed" && m.error ? h("span", { className: "sy-desc" }, String(m.error)) : null),
            h("td", { className: "sy-nowrap" }, h("select", { "data-sy": "mode-" + m.id, "aria-label": "Start mode for " + m.id, value: m.mode || "manual",
              onChange: function (e) { run(m, "/mode", { mode: e.target.value }); } },
              ["auto", "manual", "disabled"].map(function (k) {
                var mode = entry(labels.modes, k);
                return h("option", { key: k, value: k, title: mode.meaning }, mode.label);
              }))),
            h("td", { className: "sy-nowrap" }, String(m.version || "")),
            h("td", null,
              h("button", { type: "button", "data-sy": "action-" + m.id, className: "sy-button", "aria-label": model.actionName,
                "aria-disabled": model.reason ? "true" : "false", "aria-describedby": model.reason ? reasonId : null,
                onClick: function () { if (!model.reason) run(m, "/" + model.action); } }, model.actionLabel),
              model.reason ? h("span", { id: reasonId, className: "sy-reason", "data-sy": "reason-" + m.id }, model.reason,
                model.command ? h("code", null, " " + model.command) : null) : null,
              error ? h("p", { role: "alert", className: "sy-error", "data-sy": "error-" + m.id }, "Refused: " + error) : null));
        }))),
      h(Legend, { labels: labels }));
  }

  // --- Inbox view (H5 WP4; #208) -------------------------------------------------------------------------
  // Notices as the backend grouped them: when, how serious (icon, word and meaning, never colour alone),
  // labelled detail fields, repeats counted. A failed acknowledge is shown, not swallowed.
  var FILTERS = [["open", "Open"], ["acked", "Acknowledged"], ["all", "All"]];
  var EMPTY = { open: "Nothing needs your attention.", acked: "No acknowledged notices.", all: "No notices yet." };
  var ICONS = { critical: "\u25A0", high: "\u25B2", medium: "\u25C6", low: "\u25CB", info: "\u25CF" };

  function Inbox(props) {
    var filter = useState("open");
    var st = useLoad("/inbox?state=" + filter[0], props.tick, props.settled);
    var error = useState("");
    var groups = (st.data && st.data.groups) || [];

    // Acknowledge every notice in a group. What worked is shown by reloading; what did not is said.
    function send(paths) {
      var ok = 0, failed = "", left = paths.length;
      function end() {
        left -= 1;
        if (left) return;
        error[1](failed);
        if (ok) props.refresh();
      }
      paths.forEach(function (path) {
        api(path, "POST").then(function () { ok += 1; end(); },
          function (e) { failed = String((e && e.message) || e); end(); });
      });
    }

    return h("section", { "aria-labelledby": "sy-inbox-h" },
      h("h2", { id: "sy-inbox-h" }, "Inbox"),
      h("p", { className: "sy-help", "data-sy": "inbox-note" },
        "Notices from Signalbox and its modules that need a person: a module failed, a limit was reached, something was refused. " +
        "They are kept on this computer; nothing leaves this machine. They are written for you: the model cannot list or acknowledge them."),
      h("div", { role: "group", "aria-label": "Which notices to show", className: "sy-bar" },
        FILTERS.map(function (f) {
          return h("button", { type: "button", key: f[0], className: "sy-button", "data-sy": "filter-" + f[0],
            "aria-pressed": filter[0] === f[0] ? "true" : "false", onClick: function () { filter[1](f[0]); } }, f[1]);
        }),
        filter[0] === "open" && groups.length ? h("button", { type: "button", className: "sy-button", "data-sy": "ack-all",
          onClick: function () { send(["/inbox/ack_all"]); } }, "Acknowledge all") : null),
      error[0] ? h("p", { role: "alert", className: "sy-error", "data-sy": "inbox-error" }, "Could not acknowledge: " + error[0]) : null,
      st.loading && !st.data ? h(Status, { text: "Loading inbox" }) :
        st.error ? h(Status, { text: "Inbox unavailable: " + st.error }) :
          !groups.length ? h("p", { className: "sy-empty" }, EMPTY[filter[0]]) :
            h("ul", { className: "sy-notices" }, groups.map(function (g) {
              var id = g.ids[0];
              return h("li", { key: id, className: "sy-notice", "data-sy": "notice-" + id },
                h("span", { className: "sy-badge sy-sev-" + g.severity },
                  h("span", { "aria-hidden": "true" }, (ICONS[g.severity] || ICONS.info) + " "),
                  h(Term, { marker: "sev-" + id, text: String(g.severity_label || g.severity), meaning: String(g.severity_meaning || "") })),
                h("strong", { className: "sy-notice-title" }, " " + String(g.title || "")),
                h("span", { className: "sy-desc" }, "From " + String(g.module || "Signalbox") + " \u00B7 " + formatWhen(g.at) +
                  (g.count > 1 ? " \u00B7 " + times(g.count) : "") + (g.state === "acked" ? " \u00B7 Acknowledged" : "")),
                g.text ? h("p", { className: "sy-notice-text" }, String(g.text)) : null,
                g.fields && g.fields.length ? h("dl", { className: "sy-fields" }, g.fields.map(function (f, i) {
                  return h("div", { key: i }, h("dt", null, String(f.label)), h("dd", null, String(f.value)));
                })) : null,
                g.state === "open" ? h("button", { type: "button", className: "sy-button", "data-sy": "ack-" + id,
                  "aria-label": "Acknowledge: " + String(g.title || ""),
                  onClick: function () {
                    send(g.ids.map(function (one) { return "/inbox/" + encodeURIComponent(one) + "/ack"; }));
                  } }, g.count > 1 ? "Acknowledge all " + g.count : "Acknowledge") : null);
            })));
  }

  // --- Reports view (H5 WP4; #207) -----------------------------------------------------------------------
  // The answer first (one-line summary), then what the report is for, then a readable table. The stored
  // report is still there, collapsed, for anyone who wants the JSON.
  var KINDS = [["health", "Health"], ["usage", "Usage"], ["security", "Security"], ["changes", "Changes"]];

  function Table(props) {
    return h("table", { className: "sy-table" },
      h("caption", { className: "sy-caption" }, props.caption),
      h("thead", null, h("tr", null, props.columns.map(function (c) { return h("th", { scope: "col", key: c }, c); }))),
      h("tbody", null, props.rows.map(function (cells, i) {
        return h("tr", { key: i }, cells.map(function (cell, j) {
          return j ? h("td", { key: j }, cell) : h("th", { scope: "row", key: j }, cell);
        }));
      })));
  }

  function reportBody(kind, view) {
    var rows = view.rows || [];
    if (kind === "health") {
      if (!rows.length) return h("p", { className: "sy-empty" }, "No modules are installed.");
      return h(Table, { caption: "Module health", columns: ["Module", "State", "Details", "Needs"],
        rows: rows.map(function (r) { return [String(r.id), String(r.state), String(r.detail || ""), (r.needs || []).join(", ") || "Nothing"]; }) });
    }
    if (kind === "security") {
      if (!rows.length) return h("p", { className: "sy-empty" }, "Nothing was refused in the recent records.");
      return h(Table, { caption: "Recent refusals, newest first", columns: ["When", "Module", "What happened", "Permission", "Refused by", "How often"],
        rows: rows.map(function (r) {
          return [formatWhen(r.when), String(r.module || ""), String(r.what), String(r.permission || ""), String(r.who), times(r.count)];
        }) });
    }
    if (kind === "changes") {
      if (!rows.length) return h("p", { className: "sy-empty" }, "No changes in the recent records.");
      return h(Table, { caption: "Recent changes, newest first", columns: ["When", "What changed", "How often"],
        rows: rows.map(function (r) { return [formatWhen(r.when), String(r.what), times(r.count)]; }) });
    }
    var sections = view.sections || [];
    if (!sections.length) return h("p", { className: "sy-empty" }, "No module is reporting usage yet. Start the meter or router module to see it here.");
    return sections.map(function (sec) {
      return h("section", { key: sec.name, className: "sy-usage" }, h("h3", null, String(sec.name)),
        h("ul", null, (sec.lines || []).map(function (line, i) { return h("li", { key: i }, String(line)); })));
    });
  }

  function ReportBody(props) {
    var report = props.report && typeof props.report === "object" ? props.report : {};
    var summary = report.summary || {};
    var view = report.view || {};
    var raw = {};
    Object.keys(report).forEach(function (k) { if (k !== "view") raw[k] = report[k]; });
    var lines = props.kind === "health" || props.kind === "usage" ? (summary.lines || []) : [];
    return h("div", { className: "sy-report" },
      h("p", { className: "sy-headline", "data-sy": "headline", role: view.audit_ok === false ? "alert" : null }, String(summary.headline || "")),
      h("p", { className: "sy-help", "data-sy": "purpose" }, String(report.purpose || "")),
      lines.length ? h("ul", { "data-sy": "attention", "aria-label": "What needs attention" },
        lines.map(function (line, i) { return h("li", { key: i }, String(line)); })) : null,
      reportBody(props.kind, view),
      h("details", { className: "sy-raw", "data-sy": "raw" }, h("summary", null, "Raw data (JSON)"),
        h("pre", { className: "sy-pre", tabIndex: 0 }, JSON.stringify(raw, null, 2))));
  }

  function Report(props) {
    var kind = useState("health");
    var st = useLoad("/report/" + kind[0], props.tick, props.settled);
    return h("section", { "aria-labelledby": "sy-report-h" },
      h("h2", { id: "sy-report-h" }, "Reports"),
      h("p", { className: "sy-help" }, "Read-only summaries of what Signalbox has recorded on this computer. Choosing one changes nothing."),
      h("label", null, "Report ",
        h("select", { "data-sy": "report-kind", value: kind[0], onChange: function (e) { kind[1](e.target.value); } },
          KINDS.map(function (k) { return h("option", { key: k[0], value: k[0] }, k[1]); }))),
      st.loading && !st.data ? h(Status, { text: "Loading report" }) :
        st.error ? h(Status, { text: "Report unavailable: " + st.error }) :
          h(ReportBody, { report: st.data, kind: kind[0] }));
  }

  // --- Page ------------------------------------------------------------------------------------------------
  var VIEWS = [["modules", "Modules", Modules], ["inbox", "Inbox", Inbox], ["reports", "Reports", Report]];

  function Page() {
    var view = useState("modules");
    var tick = useState(0);
    var sync = useState({ loading: true, at: null });
    var count = useLoad("/inbox?state=open", tick[0]);
    function reload() { sync[1]({ loading: true, at: sync[0].at }); tick[1](tick[0] + 1); }
    function settled() { sync[1]({ loading: false, at: Date.now() }); }
    var open = (count.data && count.data.open) || 0;
    var at = sync[0].at ? new Date(sync[0].at) : null;
    var current = VIEWS.filter(function (v) { return v[0] === view[0]; })[0];
    return h("main", { className: "sy-root" },
      h("h1", null, "Signalbox"),
      h("details", { className: "sy-intro", "data-sy": "intro" },
        h("summary", null, "What is this page?"),
        h("p", null, "Signalbox adds optional modules to Hermes: small add-ons that route requests, track usage, watch for problems and more. " +
          "Each module can do only what you have permitted."),
        h("ul", null,
          h("li", null, h("strong", null, "Modules"), ": what is installed, whether it is running, and what it still needs."),
          h("li", null, h("strong", null, "Inbox"), ": notices that need a person."),
          h("li", null, h("strong", null, "Reports"), ": read-only summaries of health, usage, security and recent changes.")),
        h("p", null, "Permissions, installs, updates and removal are done from a terminal with the ", h("code", null, PROG), " command, never from this page.")),
      h("div", { role: "tablist", "aria-label": "Signalbox views", className: "sy-tabs", "data-sy": "tabs" },
        VIEWS.map(function (v) {
          var label = v[1] + (v[0] === "inbox" && open ? " (" + (open >= 200 ? "200+" : open) + " open)" : "");
          return h("button", { type: "button", role: "tab", key: v[0], id: "sy-tab-" + v[0], "data-sy": "tab-" + v[0],
            "aria-selected": view[0] === v[0] ? "true" : "false", "aria-controls": "sy-panel",
            onClick: function () { view[1](v[0]); } }, label);
        })),
      h("div", { role: "toolbar", "aria-label": "Page actions", className: "sy-bar" },
        h("button", { type: "button", className: "sy-button", "data-sy": "refresh",
          "aria-disabled": sync[0].loading ? "true" : "false",
          onClick: function () { if (!sync[0].loading) reload(); } }, sync[0].loading ? "Refreshing\u2026" : "Refresh"),
        h("span", { role: "status", "aria-live": "polite", className: "sy-desc", "data-sy": "updated" },
          at ? "Updated " + pad(at.getHours()) + ":" + pad(at.getMinutes()) + ":" + pad(at.getSeconds()) : "")),
      h("div", { role: "tabpanel", id: "sy-panel", "aria-labelledby": "sy-tab-" + view[0] },
        h(current[2], { tick: tick[0], refresh: reload, settled: settled })));
  }

  // The pure decisions and the views, for the tests that run this file under Node.
  window.__SIGNALBOX_VIEW__ = {
    safeUrl: safeUrl, hostOf: hostOf, rowModel: rowModel, sourceLinks: sourceLinks, formatWhen: formatWhen,
    Modules: Modules, Inbox: Inbox, Report: Report, Page: Page,
  };

  window.__HERMES_PLUGINS__.register("signalbox", Page);
})();
