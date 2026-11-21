DateTime? _date(Object? value) {
  if (value is! String || value.isEmpty) return null;
  return DateTime.tryParse(value)?.toLocal();
}

Map<String, dynamic> _map(Object? value) {
  if (value is Map) return Map<String, dynamic>.from(value);
  return const {};
}

List<String> _strings(Object? value) {
  if (value is! List) return const [];
  return value.whereType<Object>().map((item) => item.toString()).toList();
}

class AgentNotification {
  const AgentNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.kind,
    required this.status,
    required this.channel,
    required this.data,
    this.createdAt,
    this.readAt,
  });

  final String id;
  final String title;
  final String body;
  final String kind;
  final String status;
  final String channel;
  final Map<String, dynamic> data;
  final DateTime? createdAt;
  final DateTime? readAt;

  bool get isRead => readAt != null;
  String? get scheduleId => data['schedule_id']?.toString();
  String? get runId => data['run_id']?.toString();
  String? get agentId => data['agent_id']?.toString();

  factory AgentNotification.fromJson(Map<String, dynamic> json) {
    return AgentNotification(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? 'Agent update',
      body: json['body']?.toString() ?? '',
      kind: json['kind']?.toString() ?? 'system',
      status: json['status']?.toString() ?? 'pending',
      channel: json['channel']?.toString() ?? 'inapp',
      data: _map(json['data']),
      createdAt: _date(json['created_at']),
      readAt: _date(json['read_at']),
    );
  }
}

class AgentSchedule {
  const AgentSchedule({
    required this.id,
    required this.agentId,
    required this.name,
    required this.message,
    required this.scheduleType,
    required this.timezone,
    required this.enabled,
    required this.channels,
    required this.input,
    this.timeOfDay,
    this.weekday,
    this.intervalMinutes,
    this.quietHoursStart,
    this.quietHoursEnd,
    this.nextRunAt,
    this.lastRunAt,
    this.lastError,
  });

  final String id;
  final String agentId;
  final String name;
  final String message;
  final String scheduleType;
  final String timezone;
  final bool enabled;
  final List<String> channels;
  final Map<String, dynamic> input;
  final String? timeOfDay;
  final int? weekday;
  final int? intervalMinutes;
  final String? quietHoursStart;
  final String? quietHoursEnd;
  final DateTime? nextRunAt;
  final DateTime? lastRunAt;
  final String? lastError;

  String get cadence {
    switch (scheduleType) {
      case 'weekly':
        const days = [
          'Monday',
          'Tuesday',
          'Wednesday',
          'Thursday',
          'Friday',
          'Saturday',
          'Sunday',
        ];
        final day = (weekday ?? 0) >= 0 && (weekday ?? 0) < 7
            ? days[weekday ?? 0]
            : 'Weekly';
        return '$day ${timeOfDay ?? ''}'.trim();
      case 'interval':
        return 'Every ${intervalMinutes ?? 60} minutes';
      default:
        return 'Daily ${timeOfDay ?? ''}'.trim();
    }
  }

  factory AgentSchedule.fromJson(Map<String, dynamic> json) {
    return AgentSchedule(
      id: json['id']?.toString() ?? '',
      agentId: json['agent_id']?.toString() ?? '',
      name: json['name']?.toString() ?? 'Schedule',
      message: json['message']?.toString() ?? '',
      scheduleType: json['schedule_type']?.toString() ?? 'daily',
      timezone: json['timezone']?.toString() ?? 'UTC',
      enabled: json['enabled'] == true,
      channels: _strings(json['channels']),
      input: _map(json['input']),
      timeOfDay: json['time_of_day']?.toString(),
      weekday: json['weekday'] is num ? (json['weekday'] as num).toInt() : null,
      intervalMinutes: json['interval_minutes'] is num
          ? (json['interval_minutes'] as num).toInt()
          : null,
      quietHoursStart: json['quiet_hours_start']?.toString(),
      quietHoursEnd: json['quiet_hours_end']?.toString(),
      nextRunAt: _date(json['next_run_at']),
      lastRunAt: _date(json['last_run_at']),
      lastError: json['last_error']?.toString(),
    );
  }
}

class AgentScheduleRun {
  const AgentScheduleRun({
    required this.id,
    required this.scheduleId,
    required this.status,
    required this.result,
    required this.error,
    this.agentId,
    this.runId,
    this.scheduledFor,
    this.notificationId,
    this.startedAt,
    this.completedAt,
  });

  final String id;
  final String scheduleId;
  final String status;
  final String result;
  final String error;
  final String? agentId;
  final String? runId;
  final String? scheduledFor;
  final String? notificationId;
  final DateTime? startedAt;
  final DateTime? completedAt;

  bool get ok => status == 'ok';

  factory AgentScheduleRun.fromJson(Map<String, dynamic> json) {
    return AgentScheduleRun(
      id: json['id']?.toString() ?? '',
      scheduleId: json['schedule_id']?.toString() ?? '',
      status: json['status']?.toString() ?? 'unknown',
      result: json['result']?.toString() ?? '',
      error: json['error']?.toString() ?? '',
      agentId: json['agent_id']?.toString(),
      runId: json['run_id']?.toString(),
      scheduledFor: json['scheduled_for']?.toString(),
      notificationId: json['notification_id']?.toString(),
      startedAt: _date(json['started_at']),
      completedAt: _date(json['completed_at']),
    );
  }
}

class AgentScheduleRunDetail {
  const AgentScheduleRunDetail({required this.run, required this.timeline});

  final AgentScheduleRun run;
  final List<Map<String, dynamic>> timeline;

  factory AgentScheduleRunDetail.fromJson(Map<String, dynamic> json) {
    return AgentScheduleRunDetail(
      run: AgentScheduleRun.fromJson(_map(json['run'])),
      timeline: ((json['timeline'] as List?) ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList(),
    );
  }
}

class AgentRecipe {
  const AgentRecipe({
    required this.id,
    required this.name,
    required this.pitch,
    required this.status,
    required this.agentId,
    required this.dailyTrigger,
    required this.architecture,
    required this.requiredTools,
    required this.scheduleModes,
    required this.outputs,
    required this.whyUsersReturn,
    required this.defaultSchedule,
    this.defaultMode,
  });

  final String id;
  final String name;
  final String pitch;
  final String status;
  final String agentId;
  final String dailyTrigger;
  final String architecture;
  final List<String> requiredTools;
  final List<String> scheduleModes;
  final List<String> outputs;
  final String whyUsersReturn;
  final Map<String, dynamic> defaultSchedule;
  final String? defaultMode;

  bool get available => status == 'implemented';

  factory AgentRecipe.fromJson(Map<String, dynamic> json) {
    return AgentRecipe(
      id: json['id']?.toString() ?? '',
      name: json['name']?.toString() ?? 'Agent',
      pitch: json['pitch']?.toString() ?? '',
      status: json['status']?.toString() ?? 'planned',
      agentId: json['agent_id']?.toString() ?? '',
      dailyTrigger: json['daily_trigger']?.toString() ?? '',
      architecture: json['architecture']?.toString() ?? 'single',
      requiredTools: _strings(json['required_tools']),
      scheduleModes: _strings(json['schedule_modes']),
      outputs: _strings(json['outputs']),
      whyUsersReturn: json['why_users_return']?.toString() ?? '',
      defaultSchedule: _map(json['default_schedule']),
      defaultMode: json['default_mode']?.toString(),
    );
  }
}
