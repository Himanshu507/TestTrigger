/**
 * Test Trigger local chat client.
 *
 * Presentation only. Every decision is made by the backend: this file never
 * parses intent, selects tests, evaluates policy, polls a job, or talks to any
 * model provider. It sends a request to the local API and renders what it gets.
 */
(function () {
  "use strict";

  var API_BASE = window.TEST_TRIGGER_API_BASE || "";
  var CREATE_URL = API_BASE + "/api/v1/workflows";

  var conversation = document.getElementById("conversation");
  var form = document.getElementById("composer");
  var input = document.getElementById("query");
  var dryRun = document.getElementById("dry-run");
  var send = document.getElementById("send");

  /** Terminal statuses that are correct outcomes but not successful runs. */
  var STATUS_TONE = {
    completed: "ok",
    dry_run_complete: "warn",
    needs_clarification: "warn",
    rejected: "bad",
    retrieval_failed: "bad",
    execution_failed: "bad",
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function addMessage(role, build) {
    var message = el("article", "message " + role);
    var bubble = el("div", "bubble");
    build(bubble);
    message.appendChild(bubble);
    conversation.appendChild(message);
    conversation.scrollTop = conversation.scrollHeight;
    return message;
  }

  function statusLine(bubble, status, workflowId) {
    var line = el("div", "status-line");
    var tone = STATUS_TONE[status] || "";
    line.appendChild(el("span", "badge " + tone, humanize(status)));
    if (workflowId) line.appendChild(el("span", "workflow-id", workflowId));
    bubble.appendChild(line);
  }

  function humanize(value) {
    if (!value) return "unknown";
    return value.replace(/_/g, " ");
  }

  function section(bubble, title) {
    var wrapper = el("div", "card-section");
    wrapper.appendChild(el("h3", null, title));
    bubble.appendChild(wrapper);
    return wrapper;
  }

  function list(parent, items, className) {
    var ul = el("ul", className);
    items.forEach(function (item) {
      ul.appendChild(el("li", null, item));
    });
    parent.appendChild(ul);
    return ul;
  }

  /** Render the create-workflow response, then enrich it with the full detail. */
  function renderOutcome(bubble, summary, detail) {
    statusLine(bubble, summary.status, summary.workflow_id);

    if (summary.summary) {
      bubble.appendChild(el("p", null, summary.summary));
    }

    if (!detail) return;

    if (detail.intent && detail.intent.module) {
      var understood = section(bubble, "Understood as");
      list(understood, [
        "module: " + detail.intent.module,
        "scope: " + detail.intent.scope,
        "browser: " + detail.intent.browser,
        "region: " + detail.intent.region,
      ]);
    }

    if (detail.plan && detail.plan.tests && detail.plan.tests.length) {
      var plan = section(bubble, "Selected tests");
      detail.plan.tests.forEach(function (test) {
        var item = el("div");
        item.appendChild(el("strong", null, test.test_id));
        if (typeof test.risk_score === "number") {
          item.appendChild(el("span", "reasons", "  risk " + test.risk_score));
        }
        if (test.reasons && test.reasons.length) {
          list(item, test.reasons, "reasons");
        }
        plan.appendChild(item);
      });
    }

    if (detail.execution && detail.execution.results.length) {
      var execution = section(
        bubble,
        "Observed results — " + detail.execution.execution_id
      );
      detail.execution.results.forEach(function (result) {
        var row = el("div", "result");
        row.appendChild(
          el("span", result.status, result.status.toUpperCase() + "  ")
        );
        row.appendChild(el("span", null, result.test_id + "  " + result.duration_ms + "ms"));
        if (result.failure_reason) {
          row.appendChild(el("div", "reasons", result.failure_reason));
        }
        execution.appendChild(row);
      });
    }

    if (detail.analysis) {
      renderAnalysis(bubble, detail.analysis);
    }

    if (detail.timeline && detail.timeline.length) {
      renderTimeline(bubble, detail.timeline);
    }
  }

  /**
   * Keep observed facts visually distinct from inference. A fallback report has
   * no inferred causes at all, and says why it was degraded.
   */
  function renderAnalysis(bubble, analysis) {
    var label =
      analysis.status === "ai_generated" ? "AI analysis" : "Deterministic summary";
    var wrapper = section(bubble, label);

    wrapper.appendChild(el("p", null, analysis.summary));

    if (analysis.observations && analysis.observations.length) {
      wrapper.appendChild(el("h3", null, "Observed"));
      list(wrapper, analysis.observations);
    }

    (analysis.failures || []).forEach(function (failure) {
      var block = el("div", "inference");
      block.appendChild(el("div", "label", "Inferred — not confirmed"));
      block.appendChild(
        el(
          "p",
          null,
          failure.test_id +
            ": " +
            failure.likely_cause +
            " (confidence " +
            failure.confidence +
            ")"
        )
      );
      if (failure.recommendations && failure.recommendations.length) {
        list(block, failure.recommendations);
      }
      if (failure.evidence_source_ids && failure.evidence_source_ids.length) {
        block.appendChild(
          el("div", "sources", "evidence: " + failure.evidence_source_ids.join(", "))
        );
      }
      wrapper.appendChild(block);
    });

    if (analysis.status !== "ai_generated" && analysis.fallback_reason) {
      wrapper.appendChild(
        el("p", "hint", "AI analysis unavailable: " + analysis.fallback_reason)
      );
    }

    if (analysis.insufficient_evidence) {
      wrapper.appendChild(
        el("p", "hint", "Evidence was insufficient to explain every failure.")
      );
    }
  }

  function renderTimeline(bubble, timeline) {
    var details = el("details");
    details.appendChild(el("summary", null, "Workflow timeline"));
    var ul = el("ul", "timeline");
    timeline.forEach(function (event) {
      ul.appendChild(el("li", null, event.step + " → " + humanize(event.status)));
    });
    details.appendChild(ul);
    bubble.appendChild(details);
  }

  /** Turn an API error envelope into something a user can act on. */
  function renderError(bubble, status, payload) {
    var error = (payload && payload.error) || {};
    var code = error.code || "UNKNOWN";
    statusLine(bubble, statusForCode(code), error.workflow_id);

    bubble.appendChild(el("p", null, friendlyMessage(code, error, status)));

    var fields = (error.details || [])
      .map(function (detail) {
        return detail.field;
      })
      .filter(Boolean);

    if (code === "NEEDS_CLARIFICATION" && fields.length) {
      bubble.appendChild(el("p", "hint", "Please include: " + fields.join(", ") + "."));
    } else if (error.details && error.details.length) {
      var why = section(bubble, "Why");
      list(
        why,
        error.details.map(function (detail) {
          return detail.value || detail.field;
        })
      );
    }
  }

  function statusForCode(code) {
    if (code === "NEEDS_CLARIFICATION") return "needs_clarification";
    if (code === "EXECUTION_UNAVAILABLE") return "execution_failed";
    if (code === "RETRIEVAL_UNAVAILABLE") return "retrieval_failed";
    if (code === "MALFORMED_REQUEST") return "needs_clarification";
    return "rejected";
  }

  function friendlyMessage(code, error, status) {
    switch (code) {
      case "NEEDS_CLARIFICATION":
        return "I could not tell exactly what to run. " + (error.message || "");
      case "RETRIEVAL_UNAVAILABLE":
        return "I could not load the supporting evidence, so I stopped rather than guess. Try again shortly.";
      case "EXECUTION_UNAVAILABLE":
        return "The test runner did not finish this job. The plan was kept, so you can retry.";
      case "MALFORMED_REQUEST":
        return "That request could not be read. Try describing the tests in a sentence.";
      case "INTERNAL_ERROR":
        return "Something went wrong on the server. Nothing was executed.";
      default:
        return error.message || "The request could not be completed (HTTP " + status + ").";
    }
  }

  function setBusy(busy) {
    send.disabled = busy;
    send.textContent = busy ? "Working…" : "Send";
  }

  async function submitQuery(query, isDryRun) {
    var pending = addMessage("assistant pending", function (bubble) {
      bubble.appendChild(
        el("p", null, isDryRun ? "Planning a dry run…" : "Running your request…")
      );
    });

    var response;
    var payload;
    try {
      response = await fetch(CREATE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query, dry_run: isDryRun }),
      });
      payload = await response.json();
    } catch (networkError) {
      pending.remove();
      addMessage("assistant", function (bubble) {
        statusLine(bubble, "rejected", null);
        bubble.appendChild(
          el(
            "p",
            null,
            "I could not reach the local backend. Check that it is running, then send again."
          )
        );
      });
      return;
    }

    pending.remove();

    if (!response.ok) {
      var errorWorkflowId = payload && payload.error && payload.error.workflow_id;
      var errorDetail = errorWorkflowId ? await fetchDetail(errorWorkflowId) : null;
      addMessage("assistant", function (bubble) {
        renderError(bubble, response.status, payload);
        if (errorDetail && errorDetail.timeline) {
          renderTimeline(bubble, errorDetail.timeline);
        }
      });
      return;
    }

    var detail = await fetchDetail(payload.workflow_id);
    addMessage("assistant", function (bubble) {
      renderOutcome(bubble, payload, detail);
    });
  }

  /** Detail is an enrichment: a failure here must not lose the outcome. */
  async function fetchDetail(workflowId) {
    if (!workflowId) return null;
    try {
      var response = await fetch(API_BASE + "/api/v1/workflows/" + workflowId);
      if (!response.ok) return null;
      return await response.json();
    } catch (error) {
      return null;
    }
  }

  async function handleSubmit(event) {
    if (event) event.preventDefault();

    var query = input.value.trim();
    if (!query) {
      input.focus();
      return;
    }

    var isDryRun = dryRun.checked;
    addMessage("user", function (bubble) {
      bubble.appendChild(el("p", null, query));
      if (isDryRun) bubble.appendChild(el("p", "hint", "Dry run"));
    });

    input.value = "";
    setBusy(true);
    try {
      await submitQuery(query, isDryRun);
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  form.addEventListener("submit", handleSubmit);

  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit(event);
    }
  });
})();
