$(document).ready(function () {
    // Setup the csrf token
    var csrftoken = getCookie('csrftoken');
    $.ajaxSetup({
        beforeSend: function(xhr, settings) {
            if (!csrfSafeMethod(settings.type) && !this.crossDomain) {
                xhr.setRequestHeader("X-CSRFToken", csrftoken);
            }
        }
    });
    
    $(".read").on("click", handleClick);
    $(".reviewed").on("click", handleClick);
});

function handleClick (event) {
    // console.log("Token is " + csrftoken);
    var csrftoken = getCookie('csrftoken');
    var elem = event.target;
    var prescriptionID = elem.getAttribute("prescription_id");
    var eventType = elem.className;
    console.log("Found event of type " + eventType);
    var user = $(elem).attr("user");
    console.log("From user " + user);
    var url = makeURL(prescriptionID, eventType, user);
    console.log("Made url " + url);
    $.ajax({
            type: "POST",
            url: url,
            data: {
                event_type: eventType,
                CSRF: csrftoken,
                prescriptionID: prescriptionID,
                user: user
            }
        }
              )
            .done(function(data) {
                // Now get the new read event and update the html vals.
                console.log("Received from post " + JSON.stringify(data));
                $.get(data.created, function(data) {
                    console.log("Received from get " + JSON.stringify(data));
                    $("tr#" + data.prescription_id)
                        .find("div." + data.event_type + "_by_text")
                        .html(data.records.join("<br />"));

                    // elem.html(data.text);
                });
            })
            .fail(function () {
                alert("Failed POST");
            })
            .always(function () {
                console.log("Finished");
            });
}

function makeURL(pid, ev, u) {
    return "/report/api/v1/" + pid + "/" + ev+ "/" + u + "/";
}

// using jQuery
function getCookie(name) {
    console.log("Finding cookies");
    var cookieValue = null;
    if (document.cookie && document.cookie != '') {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = jQuery.trim(cookies[i]);
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) == (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                console.log("Found cookie");
                break;
            }
        }
    }
    return cookieValue;
}

function csrfSafeMethod(method) {
    // these HTTP methods do not require CSRF protection
    return (/^(GET|HEAD|OPTIONS|TRACE)$/.test(method));
}
