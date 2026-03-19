// calculate current_id
function getLastMsgId() {
    var msgs = [...document.querySelectorAll("#messages [id]")];
    return msgs.length === 0 ? 0 : msgs[0].id.split("_")[1];
}
function getLastPktId() {
    var msgs = [...document.querySelectorAll("#packets [id]")];
    return msgs.length === 0 ? 0 : msgs[0].id.split("_")[1];
}
function getFirstMsgId() {
    var msgs = [...document.querySelectorAll("#messages [id]")];
    return msgs.length === 0 ? 0 : msgs.pop().id.split("_")[1];
}
function getFirstPktId() {
    var msgs = [...document.querySelectorAll("#packets [id]")];
    return msgs.length === 0 ? 0 : msgs.pop().id.split("_")[1];
}

// refresh button
function manualRefresh() {
    htmx.trigger("#messages", "manual_refresh", {});
    htmx.trigger("#packets", "manual_refresh", {});
}

// scroll to bottom button
function jumpToLastMsg() {
    var msg_id = getLastMsgId();
    if (msg_id > 0) {
        document.querySelector("#message_" + msg_id).scrollIntoView();
    }
    var pkt_id = getLastPktId();
    if (pkt_id > 0) {
        document.querySelector("#packet_" + pkt_id).scrollIntoView();
    }
}

// switch tabs
function selectTab(type) {
    document.querySelectorAll(".tab-button").forEach(button => {
        button.classList.toggle("outline");
        button.classList.toggle("secondary");
    });
    document.querySelectorAll(".messages").forEach(messages => {
        messages.hidden = (messages.id !== type)
    })
}
