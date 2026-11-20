import '../utils/ids.dart';

class FocusSession {
  const FocusSession({
    required this.id,
    required this.label,
    required this.startedAt,
    required this.plannedMinutes,
    this.endedAt,
    this.completed = false,
  });

  final String id;
  final String label;
  final DateTime startedAt;
  final int plannedMinutes;
  final DateTime? endedAt;
  final bool completed;

  bool get isActive => endedAt == null;
  int get plannedMs => plannedMinutes * 60 * 1000;
  int get durationMs =>
      (endedAt ?? DateTime.now().toUtc()).difference(startedAt).inMilliseconds;

  FocusSession finish({bool completed = false}) => FocusSession(
    id: id,
    label: label,
    startedAt: startedAt,
    plannedMinutes: plannedMinutes,
    endedAt: DateTime.now().toUtc(),
    completed: completed,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'label': label,
    'started_at': isoUtc(startedAt),
    if (endedAt != null) 'ended_at': isoUtc(endedAt!),
    'planned_minutes': plannedMinutes,
    'completed': completed,
  };

  static FocusSession fromJson(Map<String, dynamic> json) => FocusSession(
    id: (json['id'] ?? newUuidV4()).toString(),
    label: (json['label'] ?? 'Focus').toString(),
    startedAt: parseUtc(json['started_at']) ?? DateTime.now().toUtc(),
    endedAt: parseUtc(json['ended_at']),
    plannedMinutes: (json['planned_minutes'] as num?)?.toInt() ?? 25,
    completed: json['completed'] == true,
  );
}
