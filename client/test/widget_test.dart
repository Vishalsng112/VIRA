import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:client/main.dart';
import 'package:client/local_replica.dart';

void main() {
  testWidgets('shows the VIRA connection form', (tester) async {
    await tester.pumpWidget(const ViraApp());
    expect(find.text('VIRA'), findsOneWidget);
    expect(find.text('Connect'), findsOneWidget);
    expect(find.text('Server URL'), findsOneWidget);
  });

  test('persists and removes outbox operations', () async {
    SharedPreferences.setMockInitialValues({});
    final replica = await LocalReplica.open();
    await replica.enqueue('household-1', {
      'op_id': 'op-1',
      'entity_type': 'note',
    });
    expect(replica.pendingOps('household-1'), hasLength(1));
    await replica.removePending('household-1', {'op-1'});
    expect(replica.pendingOps('household-1'), isEmpty);
  });
}
