// calculate current_id
function getLastMsgId() {
    let msgs = [...document.querySelectorAll("#messages [id]")];
    return msgs.length === 0 ? 0 : msgs[0].id.split("_")[1];
}
function getLastPktId() {
    let pkts = [...document.querySelectorAll("#packets [id]")];
    return pkts.length === 0 ? 0 : pkts[0].id.split("_")[1];
}
function getFirstMsgId() {
    let msgs = [...document.querySelectorAll("#messages [id]")];
    return msgs.length === 0 ? 0 : msgs.pop().id.split("_")[1];
}
function getFirstPktId() {
    let pkts = [...document.querySelectorAll("#packets [id]")];
    return pkts.length === 0 ? 0 : pkts.pop().id.split("_")[1];
}

// page cleanup
function msgCleanUp() {
    let msgs = [...document.querySelectorAll("#messages [id]")].reverse();
    let buffer_size = 100;
    for (let i = 0; i < msgs.length; i++) {
        if (i + buffer_size > msgs.length - 1) return;  // oob
        if (msgs[i + buffer_size].getBoundingClientRect().top <= 0) {
            msgs[i].closest(".msg-div").remove();
        } else return;
    }
}
function pktCleanUp() {
    let pkts = [...document.querySelectorAll("#packets [id]")].reverse();
    let buffer_size = 100;
    for (let i = 0; i < pkts.length; i++) {
        if (i + buffer_size > pkts.length - 1) return;  // oob
        if (pkts[i + buffer_size].getBoundingClientRect().top <= 0) {
            pkts[i].closest(".pkt-div").remove();
        } else return;
    }
}

// refresh button
function manualRefresh() {
    htmx.trigger("#messages", "manual_refresh", {});
    htmx.trigger("#packets", "manual_refresh", {});
}

// scroll to bottom button
function jumpToLastMsg() {
    let msg_id = getLastMsgId();
    if (msg_id > 0) {
        document.querySelector("#message_" + msg_id).scrollIntoView();
    }
    let pkt_id = getLastPktId();
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
