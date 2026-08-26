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
        var resp = await fetch("/create", { method: "POST" });
        if (!resp.ok) return result("Error " + resp.status + ".");
        var page = resp.url;
        setTimeout(function () { location.assign(page); }, 500);
        return result(
          "Feed created. Its private page is " + page + " (treat it as a secret; it is the user's whole account). " +
          "Navigating there now; the article tools register on that page."
        );
      }
    });
  }

  if (!tools.length) return;
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
