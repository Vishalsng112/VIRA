import '../utils/ids.dart';

enum EventDeliveryState { pending, sent, rejected }

/// One event produced on the device. It is stored in the outbox before any
/// network call, so losing connectivity never loses the payload.
class CapturedEvent {
  const CapturedEvent({
    required this.eventId,
    required this.type,
    required this.occurredAt,
    required this.sourceComponent,
    required this.payload,
    this.deviceSequence,
    this.capturedAt,
    this.deliveryState = EventDeliveryState.pending,
    this.error,
  });

  final String eventId;
  final String type;
  final DateTime occurredAt;
  final String sourceComponent;
  final Map<String, dynamic> payload;
  final int? deviceSequence;
  final DateTime? capturedAt;
  final EventDeliveryState deliveryState;
  final String? error;

  CapturedEvent copyWith({
    int? deviceSequence,
    DateTime? capturedAt,
    EventDeliveryState? deliveryState,
    String? error,
  }) => CapturedEvent(
    eventId: eventId,
    type: type,
    occurredAt: occurredAt,
    sourceComponent: sourceComponent,
    payload: payload,
    deviceSequence: deviceSequence ?? this.deviceSequence,
    capturedAt: capturedAt ?? this.capturedAt,
    deliveryState: deliveryState ?? this.deliveryState,
    error: error ?? this.error,
  );

  /// The public device ingestion shape. Server resolves identity from the
  /// device credential; the body never carries a device id or user id.
  Map<String, dynamic> toIngestJson() => {
    'event_id': eventId,
    'type': type,
    'schema_version': 1,
    'occurred_at': isoUtc(occurredAt),
    'source_component': sourceComponent,
    if (deviceSequence != null) 'device_sequence': deviceSequence,
    'payload': payload,
  };

  Map<String, dynamic> toJson() => {
    ...toIngestJson(),
    'captured_at': capturedAt == null ? null : isoUtc(capturedAt!),
    'delivery_state': deliveryState.name,
    if (error != null) 'error': error,
  };

  static CapturedEvent fromJson(Map<String, dynamic> json) => CapturedEvent(
    eventId: json['event_id'] as String,
    type: json['type'] as String,
    occurredAt:
        parseUtc(json['occurred_at']) ?? DateTime.now().toUtc(),
    sourceComponent: json['source_component'] as String? ?? 'vira_link',
    payload: Map<String, dynamic>.from(
      (json['payload'] as Map?) ?? const <String, dynamic>{},
    ),
    deviceSequence: (json['device_sequence'] as num?)?.toInt(),
    capturedAt: parseUtc(json['captured_at']),
    deliveryState: EventDeliveryState.values.firstWhere(
      (value) => value.name == json['delivery_state'],
      orElse: () => EventDeliveryState.pending,
    ),
    error: json['error'] as String?,
  );
}
