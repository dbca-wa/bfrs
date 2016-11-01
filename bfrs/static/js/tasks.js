/*
 * FullCalendar v1.5.4 Tasks plugin
 *
 * Copyright (c) 2013 Department of Environment and Conservation
 *
 */
(function($) {

var fc = $.fullCalendar;
var formatDate = fc.formatDate;
var parseISO8601 = fc.parseISO8601;
var addDays = fc.addDays;
var applyAll = fc.applyAll;


fc.sourceNormalizers.push(function(sourceOptions) {
	if (sourceOptions.dataType === 'tasks' ||
		sourceOptions.dataType === undefined &&
		(sourceOptions.url || '').match(/api\/tasks\//)) {
			sourceOptions.dataType = 'tasks';
			if (sourceOptions.editable === undefined) {
				sourceOptions.editable = true;
				sourceOptions.disableResizing = true;
			}
		}
});


fc.sourceFetchers.push(function(sourceOptions, start, end) {
	if (sourceOptions.dataType === 'tasks') {
		return transformOptions(sourceOptions, start, end);
	}
});


function transformOptions(sourceOptions, start, end) {

	var success = sourceOptions.success;
	var data = $.extend({}, sourceOptions.data || {}, {
		'due_date_min': formatDate(start, 'yyyy-MM-dd'),
		'due_date_max': formatDate(end, 'yyyy-MM-dd'),
	});
	
	return $.extend({}, sourceOptions, {
		dataType: 'json',
		data: data,
		startParam: false,
		endParam: false,
		success: function(data) {
			var events = [];
			if (data) {
				$.each(data, function(i, result) {
                    var date;
                    var color;
                    if (result.complete_date !== null) {
                        date = parseISO8601(result.complete_date, true);
                        color = '#DFF0D8';
                    } else {
                        date = parseISO8601(result.due_date, true);
                        if (date.getTime() < new Date().getTime()) {
                            color = '#F2DEDE';
                        } else {
                            color = '#D9EDF7';
                        }
                    }
					events.push({
						id: result.url,
						title: 'Task for ' + result.referral + ' (' + result.type + ')',
						start: date,
						location: '',
						description: result.description,
                        color: color,
                        task: result,
                        textColor: '#000000'
					});
				});
			}
			var args = [events].concat(Array.prototype.slice.call(arguments, 1));
			var res = applyAll(success, this, args);
			if ($.isArray(res)) {
				return res;
			}
			return events;
		}
	});
	
}
})(jQuery);
