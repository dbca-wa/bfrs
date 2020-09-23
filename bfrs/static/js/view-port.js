/*
 Module: view-port.js

 Exports: viewPort object with public methods:
        save: Save the current view port.
        update: Update the current view port to a previously saved state

 Dependencies : $ (Jquery)

 Use:
 Include the script in the template with

    <script src="{% static 'js/view-port.js' %}"></script>

 On post call viewPort.save()

 On ready call viewPort.update()

 e.g.
 $(document).ready(function () {
     viewPort.update();
 })


<script src="{% static 'js/view-port.js' %}"></script>
<script>$(document).ready(function () {viewPort.update();});
        $('#id_save_submit_button').click(function() {viewPort.save();}); </script>


 The current storage mechanism is the window.name
 but LocalStorage or SessionStorage on the url key
 may play better among different pages.

 Using window.name bleeds between pages.
 Better to use sessionStorage keyed by url.

*/

var viewPort = (function viewPort (window, document, $) {
    'use strict';

    var __debug__ = false;
    var sep = ":";
    var store = sessionStorage;

    var log = function log () {
        if (__debug__) {
            console.log.apply(console, arguments);
        }
    };

    var pack = function pack (port) {
        var name = "viewPort:" + port.left.toString() + ":" + port.top.toString()
            + ":" + port.width.toString() + ":" + port.height.toString();
        return name;
    };

    var unpack = function unpack (value) {
        var elems = value.split(sep);
        var port = {
            left   : parseFloat(elems[1]),
            top    : parseFloat(elems[2]),
            width  : parseFloat(elems[3]),
            height : parseFloat(elems[4])
        };
        return port;
    };

    var get = function get (window) {
        var $w = $(window);
        var port = {
            left   : $w.scrollLeft(),
            top    : $w.scrollTop(),
            width  : $w.width(),
            height : $w.height()
        };
        return port;
    };

    var set = function set (window, port) {
        var $w = $(window);
        $w.scrollLeft(port.left);
        $w.scrollTop(port.top);
        $w.width(port.width);
        $w.height(port.height);
    };

    var sink = function sink (store, window, port) {
        var key = window.location.href;
        var value = pack(port);
        store.setItem(key, value);
    };

    // source: store, window -> port
    // Return the coords of the previous view port.
    var source = function source (store, window) {
        var key = window.location.href;
        var value = store.getItem(key) || "viewPort:0:0:0:0";
        var port = unpack(value);
        log("Found window name: " + value);
        return port;
    };

    var save = function save () {
        var port = get(window);
        sink(store, window, port);
        log("Saving view port as ");
        log(port);
    };

    var update = function update () {
        var port = source(store, window);
        log("Setting view port to:");
        log(port);
        set(window, port);
    };

    var module = {
        save: save,
        update: update
    };
    return module;
}(window, document, $));
