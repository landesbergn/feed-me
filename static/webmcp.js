/* Feed Me WebMCP tools.
 *
 * When this page is opened in a WebMCP-capable agent browser (ChatGPT's
 * browser, or Chrome with WebMCP enabled), register tools that drive the
 * same agent API documented at /AGENTS.md: create_feed on the landing page,
 * the full episode toolset on the feed page. Everywhere else, and in every
 * browser without WebMCP, this script is a silent no-op.
 *
 * The API is an origin trial and has moved between drafts (navigator vs
 * document home, registerTool vs provideContext), so detect every shape and
 * never let a registration failure escape to the page.
 */
(function () {
  "use strict";

  var mc = (typeof navigator !== "undefined" && navigator.modelContext) ||
    (typeof document !== "undefined" && document.modelContext);
  if (!mc) return;

  var match = location.pathname.match(/^\/u\/([A-Za-z0-9_-]+)(\/collab)?\/?$/);
  var secret = match ? match[1] : null;
  var onCollab = !!(match && match[2]);

  function result(text) {
    return { content: [{ type: "text", text: text }] };
  }

  /* Same-origin fetch -> {ok, text}. Error bodies from the agent API are
     {"error","message"} JSON; anything else becomes a bare status line. */
  async function call(method, path, options) {
    options = options || {};
    var init = { method: method, headers: {} };
    if (options.json) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.json);
    }
    if (options.form) {
      init.body = new URLSearchParams(options.form);
    }
    var resp = await fetch(path, init);
    var body = await resp.text();
    if (!resp.ok) {
      try {
        var err = JSON.parse(body);
        if (err && err.error && err.message) {
          return { ok: false, text: "Error " + resp.status + " (" + err.error + "): " + err.message };
        }
      } catch (e) { /* not the agent API's JSON shape */ }
      return { ok: false, text: "Error " + resp.status + "." };
    }
    return { ok: true, text: body };
  }

  var tools = [];

  if (secret) {
    var base = "/u/" + secret;

    tools.push({
      name: "add_article",
      description: "Narrate an article into this Feed Me podcast feed from its URL. Returns the pending episode as JSON (note the slug); narration takes a few minutes, so poll get_episode_status until status is ready. Do not retry a failed URL.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "The article's http or https URL." }
        },
        required: ["url"]
      },
      execute: async function (params) {
        var r = await call("POST", base + "/episodes", { json: { url: params.url } });
        return result(r.ok ? "Episode created: " + r.text : r.text);
      }
    });

    tools.push({
      name: "add_article_text",
      description: "Narrate text you already have into this feed: an article a server fetch cannot reach, or writing of your own the user asked for. Requires a title. Returns the pending episode as JSON; poll get_episode_status until ready.",
      inputSchema: {
        type: "object",
        properties: {
          text: { type: "string", description: "The full text to narrate." },
          title: { type: "string", description: "The episode title." },
          url: { type: "string", description: "Optional source URL for the show notes." }
        },
        required: ["text", "title"]
      },
      execute: async function (params) {
        var payload = { text: params.text, title: params.title };
        if (params.url) payload.url = params.url;
        var r = await call("POST", base + "/episodes", { json: payload });
        return result(r.ok ? "Episode created: " + r.text : r.text);
      }
    });

    tools.push({
      name: "list_episodes",
      description: "List this feed's 20 most recent episodes, newest first, with per-episode status, plus the feed's voice and the remaining daily share quota.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        var r = await call("GET", base + "/episodes");
        return result(r.text);
      }
    });

    tools.push({
      name: "get_episode_status",
      description: "Check one episode by slug. Status moves from pending to ready (an audio_url appears) or failed (error says why). Narration takes a few minutes; poll no faster than every few seconds.",
      inputSchema: {
        type: "object",
        properties: {
          slug: { type: "string", description: "The episode slug returned by add_article or add_article_text." }
        },
        required: ["slug"]
      },
      execute: async function (params) {
        var r = await call("GET", base + "/episodes/" + encodeURIComponent(params.slug));
        return result(r.text);
      }
    });

    tools.push({
      name: "delete_episode",
      description: "Delete one episode from the feed by slug. This cannot be undone, so confirm with the user before deleting anything they did not just ask you to remove.",
      inputSchema: {
        type: "object",
        properties: {
          slug: { type: "string", description: "The episode slug to delete." }
        },
        required: ["slug"]
      },
      execute: async function (params) {
        var r = await call("DELETE", base + "/episodes/" + encodeURIComponent(params.slug));
        return result(r.text);
      }
    });

    tools.push({
      name: "set_voice",
      description: "Set the narration voice for future episodes of this feed. Already-narrated episodes keep their voice.",
      inputSchema: {
        type: "object",
        properties: {
          voice: {
            type: "string",
            "enum": ["alloy", "echo", "nova", "shimmer"],
            description: "The voice name."
          }
        },
        required: ["voice"]
      },
      execute: async function (params) {
        var r = await call("POST", base + "/voice", { form: { voice: params.voice } });
        return result(r.ok ? "Voice set to " + params.voice + " for future episodes." : r.text);
      }
    });

    tools.push({
      name: "get_feed_info",
      description: "Get this feed's page URL and its private RSS URL for subscribing in a podcast app. Both URLs are this user's whole account: treat them as secrets and share them only with the user.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        return result(JSON.stringify({
          feed_page: location.origin + base,
          feed_url: location.origin + base + "/feed.xml",
          api_docs: location.origin + "/AGENTS.md"
        }));
      }
    });
  } else if (location.pathname === "/") {
    tools.push({
      name: "create_feed",
      description: "Create a new private Feed Me podcast feed for this user, then go to its feed page, where the tools for adding articles register. One feed per person is plenty: do not call this if the user already has a feed.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        /* Press the page's own button, visibly, before doing its work. */
        try {
          var cta = document.querySelector("button.cta");
          if (cta) {
            cta.scrollIntoView({ behavior: "smooth", block: "center" });
            cta.style.transition = "box-shadow .3s ease";
            cta.style.boxShadow = "0 0 0 3px #b04a00, 0 0 18px rgba(176,74,0,.35)";
          }
        } catch (e) { /* flourish */ }
        var resp = await fetch("/create", { method: "POST" });
        if (!resp.ok) return result("Error " + resp.status + ".");
        var page = resp.url;
        try { sessionStorage.setItem("fmAgentCreated", "1"); } catch (e) {}
        setTimeout(function () { location.assign(page + "/collab"); }, 500);
        return result(
          "Feed created. Its private page is " + page + " (treat it as a secret; it is the user's whole account). " +
          "Navigating to its agent session view now. Stay on that page: it is where the article tools register " +
          "and where the user watches you work. Do not navigate elsewhere or open the settings page unless the user asks."
        );
      }
    });
  }

  if (!tools.length) return;

  /* Agent mode: the first tool call flips the page into a visible agent
     state (a pinned banner with a live activity line), so the person
     watching knows their agent is driving. Pure flourish: a failure here
     must never break the tool call itself. */
  var ACTIVITY = {
    add_article: "adding an article",
    add_article_text: "narrating supplied text",
    list_episodes: "reading the episode list",
    get_episode_status: "checking narration progress",
    delete_episode: "deleting an episode",
    set_voice: "changing the voice",
    get_feed_info: "reading the feed links",
    create_feed: "creating your feed"
  };
  var bannerText = null;

  /* The activity log: a persisted play-by-play of what the agent did,
     rendered natively on the /collab page and carried across navigations
     (create_feed's hop, the classic page's first-call hop) in
     sessionStorage. Entries are this script's own fixed strings only,
     never tool inputs, so nothing injected can enter the DOM here. */
  var LOG_KEY = "fmAgentLog";

  function readLog() {
    try { return JSON.parse(sessionStorage.getItem(LOG_KEY)) || []; }
    catch (e) { return []; }
  }

  function renderLog() {
    try {
      var ol = document.getElementById("agent-log");
      if (!ol) return;
      var entries = readLog();
      ol.innerHTML = "";
      for (var i = entries.length - 1; i >= 0; i--) {
        var li = document.createElement("li");
        var when = document.createElement("span");
        when.className = "log-time";
        when.textContent = new Date(entries[i].t).toLocaleTimeString();
        var what = document.createElement("span");
        what.textContent = entries[i].m;
        li.appendChild(when);
        li.appendChild(what);
        ol.appendChild(li);
      }
      var empty = document.getElementById("log-empty");
      if (empty) empty.hidden = entries.length > 0;
    } catch (e) { /* flourish */ }
  }

  function logActivity(message) {
    try {
      var entries = readLog();
      if (entries.length && entries[entries.length - 1].m === message) return;
      entries.push({ t: Date.now(), m: message });
      sessionStorage.setItem(LOG_KEY, JSON.stringify(entries.slice(-50)));
    } catch (e) { /* sessionStorage can be unavailable; the strip still works */ }
    renderLog();
  }

  function agentMode(message, quiet) {
    var status = document.getElementById("agent-status-text");
    if (status) {
      try { status.textContent = message; } catch (e) { /* flourish */ }
    } else {
      injectedBanner(message);
    }
    if (!quiet) logActivity(message);
  }

  function injectedBanner(message) {
    try {
      if (!bannerText) {
        var banner = document.createElement("div");
        banner.id = "fm-agent-banner";
        banner.setAttribute("role", "status");
        banner.setAttribute("aria-live", "polite");
        banner.style.cssText =
          "position:fixed;top:0;left:0;right:0;z-index:9999;" +
          "display:flex;align-items:center;justify-content:center;gap:8px;" +
          "padding:9px 16px;background:#2a1f18;color:#FFF8F2;" +
          "font:600 13px/1.4 -apple-system,'Helvetica Neue',system-ui,sans-serif;" +
          "box-shadow:0 2px 10px rgba(42,31,24,.25);";
        var pulse = document.createElement("style");
        pulse.textContent =
          "@keyframes fm-agent-pulse{0%,100%{opacity:1}50%{opacity:.3}}";
        var dot = document.createElement("span");
        dot.style.cssText =
          "width:8px;height:8px;border-radius:50%;background:#7ddb8a;" +
          "flex:none;animation:fm-agent-pulse 1.6s ease-in-out infinite;";
        var label = document.createElement("span");
        label.textContent = "Agent mode";
        bannerText = document.createElement("span");
        bannerText.style.cssText = "font-weight:400;opacity:.9;";
        banner.appendChild(pulse);
        banner.appendChild(dot);
        banner.appendChild(label);
        banner.appendChild(bannerText);
        document.body.appendChild(banner);
        document.body.style.marginTop =
          ((parseFloat(getComputedStyle(document.body).marginTop) || 0) + 38) + "px";
      }
      bannerText.textContent = "· " + message;
    } catch (e) { /* never break a tool call over a banner */ }
  }

  /* Page reactions: each tool call drives the same UI a person would use,
     so watching the page shows the collaboration, not just the end result.
     All flourish: a reaction failure never breaks the tool call. */
  function flash(el) {
    try {
      if (!el) return;
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.style.transition = "box-shadow .3s ease";
      el.style.borderRadius = el.style.borderRadius || "10px";
      el.style.boxShadow = "0 0 0 3px #b04a00, 0 0 18px rgba(176,74,0,.35)";
      setTimeout(function () { el.style.boxShadow = ""; }, 1600);
    } catch (e) { /* flourish */ }
  }

  async function refreshEpisodes() {
    try {
      var target = document.getElementById("episodes-section");
      if (!target) return null;
      var resp = await fetch("/u/" + secret + "/episodes_partial", { cache: "no-store" });
      if (resp.ok) target.innerHTML = await resp.text();
      return target;
    } catch (e) { return null; }
  }

  var REACT = {
    add_article: async function () { flash(await refreshEpisodes()); },
    add_article_text: async function () { flash(await refreshEpisodes()); },
    delete_episode: async function () { flash(await refreshEpisodes()); },
    list_episodes: function () { flash(document.getElementById("episodes-section")); },
    /* Status checks repeat while polling: keep the table fresh, no scrolling. */
    get_episode_status: async function () { await refreshEpisodes(); },
    set_voice: function (params) {
      var settings = document.querySelector("details.settings");
      if (settings) settings.open = true;
      var chips = document.querySelectorAll(".voice-chip");
      for (var i = 0; i < chips.length; i++) {
        chips[i].classList.toggle(
          "active", chips[i].textContent.trim() === params.voice);
      }
      flash(document.querySelector(".voices"));
    },
    get_feed_info: function () {
      var fold = document.querySelector("details.setup-fold");
      if (fold) fold.open = true;
      flash(document.querySelector("a.btn-primary"));
    }
  };

  var hopped = false;

  tools = tools.map(function (tool) {
    var inner = tool.execute;
    tool.execute = async function (params) {
      var activity = ACTIVITY[tool.name] || "working";
      /* Status polling repeats: keep it off the timeline. */
      var quiet = tool.name === "get_episode_status";
      agentMode("your agent is " + activity + "...", quiet);
      try {
        var out = await inner.apply(this, arguments);
        agentMode("your agent finished " + activity, quiet);
        var react = REACT[tool.name];
        if (react) { try { await react(params); } catch (e) { /* flourish */ } }
        /* First completed call on the classic feed page: move the person to
           the agent-session view. Only between calls, never mid-call; the
           tools re-register there. */
        if (secret && !onCollab && !hopped) {
          hopped = true;
          setTimeout(function () {
            location.assign("/u/" + secret + "/collab");
          }, 700);
        }
        return out;
      } catch (e) {
        agentMode("the last request failed");
        throw e;
      }
    };
    return tool;
  });

  /* On arrival: restore the carried activity log, and if the agent just
     created this feed, greet the person in agent mode right away instead of
     a page that looks untouched until the next tool call. */
  if (secret) {
    renderLog();
    try {
      if (sessionStorage.getItem("fmAgentCreated")) {
        sessionStorage.removeItem("fmAgentCreated");
        agentMode("your agent created this feed");
        flash(document.getElementById("episodes-section"));
      }
    } catch (e) { /* sessionStorage can be unavailable; fine */ }
  }

  try {
    if (typeof mc.registerTool === "function") {
      for (var i = 0; i < tools.length; i++) mc.registerTool(tools[i]);
    } else if (typeof mc.provideContext === "function") {
      mc.provideContext({ tools: tools });
    }
  } catch (e) {
    /* An API-shape drift must never break the page. */
  }
})();
