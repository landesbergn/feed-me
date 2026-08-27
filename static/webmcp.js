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

  var match = location.pathname.match(/^\/u\/([A-Za-z0-9_-]+)\/?$/);
  var secret = match ? match[1] : null;

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
      description: "Narrate an article into this Feed Me podcast feed from its URL. You are the feed's producer: pass a one-line note about why you picked this and it appears in the episode's show notes. Returns the pending episode as JSON (note the slug); narration takes a few minutes, so poll get_episode_status until status is ready. Do not retry a failed URL.",
      inputSchema: {
        type: "object",
        properties: {
          url: { type: "string", description: "The article's http or https URL." },
          note: { type: "string", description: "Optional producer's note to the listener, one line, max 300 characters. Shown in the episode's show notes." }
        },
        required: ["url"]
      },
      execute: async function (params) {
        var payload = { url: params.url };
        if (params.note) payload.note = params.note;
        var r = await call("POST", base + "/episodes", { json: payload });
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
          url: { type: "string", description: "Optional source URL for the show notes." },
          note: { type: "string", description: "Optional producer's note to the listener, one line, max 300 characters. Shown in the episode's show notes." }
        },
        required: ["text", "title"]
      },
      execute: async function (params) {
        var payload = { text: params.text, title: params.title };
        if (params.url) payload.url = params.url;
        if (params.note) payload.note = params.note;
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
      name: "get_requests",
      description: "The user's standing requests for you, their feed's producer: things they want narrated, plus feedback taps from their podcast app ('More like ...'). Call this at the start of any session on this page and fulfill what you can. Complete fulfilled ones with complete_request.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        var r = await call("GET", base + "/requests");
        return result(r.text);
      }
    });

    tools.push({
      name: "complete_request",
      description: "Mark one of the user's requests done, with an optional one-line note about what you produced for it. Call after fulfilling a request from get_requests.",
      inputSchema: {
        type: "object",
        properties: {
          id: { type: "string", description: "The request id from get_requests." },
          note: { type: "string", description: "Optional one-line note about what you did." }
        },
        required: ["id"]
      },
      execute: async function (params) {
        var payload = params.note ? { note: params.note } : {};
        var r = await call("POST", base + "/requests/" + encodeURIComponent(params.id) + "/complete", { json: payload });
        return result(r.text);
      }
    });

    tools.push({
      name: "help_subscribe",
      description: "Help the user put this feed in their podcast app. Call this right after create_feed, or whenever the user wants to subscribe. It highlights the subscribe buttons on the page and copies the private RSS link to the user's clipboard when the browser allows. Relay the returned instructions to the user.",
      inputSchema: { type: "object", properties: {} },
      execute: async function () {
        var rss = location.origin + base + "/feed.xml";
        flash(document.getElementById("listen-card"));
        var copied = false;
        try {
          await navigator.clipboard.writeText(rss);
          copied = true;
          var note = document.getElementById("agent-copied");
          if (note) note.hidden = false;
        } catch (e) { /* clipboard needs focus or a gesture; the page has a Copy button */ }
        return result(
          "The page is highlighting the subscribe buttons. " +
          (copied
            ? "The RSS link is on the user's clipboard. "
            : "The clipboard was not available here, so the link was not copied. ") +
          "Tell the user: tap Add to Apple Podcasts on the page (Overcast and Pocket Casts buttons are there too)" +
          (copied
            ? ", or paste the copied link into any other podcast app."
            : ", or use the Copy RSS link button for any other podcast app. The RSS link is " + rss) +
          " Subscribing once is enough; every future episode arrives automatically."
        );
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
      description: "Create a new private Feed Me podcast feed for this user, then go to its feed page, where the tools for adding articles register. Free and instant: no signup, no payment, nothing is shared anywhere, and an unwanted feed can simply be abandoned. When the user asks for a feed, that is the consent; call this directly with no extra confirmation. One feed per person is plenty: do not call this if the user already has a feed.",
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
        setTimeout(function () { location.assign(page); }, 500);
        return result(
          "Feed created. Its private page is " + page + " (treat it as a secret; it is the user's whole account). " +
          "Navigating there now; the feed tools register on that page. " +
          "Next step: call help_subscribe to help the user put the feed in their podcast app. " +
          "Stay on that page; do not navigate elsewhere unless the user asks."
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
    help_subscribe: "helping you subscribe",
    get_requests: "checking your requests",
    complete_request: "checking off a request",
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
    var trace = document.getElementById("agent-trace");
    var traceText = document.getElementById("agent-trace-text");
    if (trace && traceText) {
      try {
        trace.hidden = false;
        traceText.textContent = message;
      } catch (e) { /* flourish */ }
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

  async function refreshRequests() {
    try {
      var target = document.getElementById("requests-section");
      if (!target) return null;
      var resp = await fetch("/u/" + secret + "/requests_partial", { cache: "no-store" });
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
      flash(document.getElementById("listen-card") || document.querySelector("a.btn-primary"));
    },
    get_requests: function () {
      flash(document.getElementById("requests-section"));
    },
    complete_request: async function () {
      flash(await refreshRequests());
    }
  };

  tools = tools.map(function (tool) {
    var inner = tool.execute;
    tool.execute = async function (params) {
      var activity = ACTIVITY[tool.name] || "working";
      /* Status polling repeats: keep it off the timeline. */
      var quiet = tool.name === "get_episode_status";
      agentMode("your producer is " + activity + "...", quiet);
      try {
        var out = await inner.apply(this, arguments);
        agentMode("your producer finished " + activity, quiet);
        var react = REACT[tool.name];
        if (react) { try { await react(params); } catch (e) { /* flourish */ } }
        return out;
      } catch (e) {
        agentMode("the last request failed");
        throw e;
      }
    };
    return tool;
  });

  /* On arrival: restore the carried activity log, wire the history toggle,
     and if the agent just created this feed, greet the person in agent mode
     right away instead of a page that looks untouched until the next call. */
  if (secret) {
    renderLog();
    var historyBtn = document.getElementById("agent-history-btn");
    if (historyBtn) {
      historyBtn.addEventListener("click", function () {
        var log = document.getElementById("agent-log");
        if (log) log.hidden = !log.hidden;
      });
    }
    try {
      if (sessionStorage.getItem("fmAgentCreated")) {
        sessionStorage.removeItem("fmAgentCreated");
        agentMode("your producer created this feed");
        flash(document.getElementById("listen-card"));
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
