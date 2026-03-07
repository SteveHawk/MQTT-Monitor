// calculate current_id to avoid missing messages
function getMsgId() {
    var msgs = [...document.querySelectorAll("#messages [id]")];
    return msgs.length === 0 ? 0 : msgs[0].id.split("_")[1];
}

// refresh button
function manualRefresh() {
    htmx.trigger("#messages", "manual_refresh", {})
}

// scroll to bottom button
function jumpToLastMsg() {
    document.querySelector("#message_" + getMsgId()).scrollIntoView();
}