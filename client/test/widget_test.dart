import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:vira_link/core/models/captured_event.dart';
import 'package:vira_link/core/utils/ids.dart';
import 'package:vira_link/data/api/vira_api.dart';
import 'package:vira_link/data/storage/outbox_store.dart';

void main() {
  test('generates RFC-4122 v4 ids', () {
    final id = newUuidV4();
    expect(
      RegExp(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
      ).hasMatch(id),
      isTrue,
    );
    expect(newUuidV4(), isNot(id));
  });

  test('queues events offline, assigns a sequence and settles them', () async {
    SharedPreferences.setMockInitialValues({});
    final outbox = await OutboxStore.open();
    final event = CapturedEvent(
      eventId: newUuidV4(),
      type: 'device.telemetry.test',
      occurredAt: DateTime.now().toUtc(),
      sourceComponent: 'vira_link',
      payload: const {'message': 'hello'},
    );

    final stored = await outbox.enqueue(event);
    expect(stored.deviceSequence, 1);
    expect(await outbox.depth(), 1);

    final pending = await outbox.pending();
    expect(pending.single.eventId, event.eventId);
    expect(pending.single.toIngestJson()['device_sequence'], 1);

    await outbox.settle({event.eventId: EventDeliveryState.sent});
    expect(await outbox.depth(), 0);
    expect((await outbox.history()).single.deliveryState, EventDeliveryState.sent);
  });

  test('normalises server URLs', () {
    expect(
      ViraApi.normalizeBaseUrl('192.168.1.20:8000/'),
      'http://192.168.1.20:8000',
    );
    expect(
      ViraApi.normalizeBaseUrl('https://vira.example.com/'),
      'https://vira.example.com',
    );
  });
}
