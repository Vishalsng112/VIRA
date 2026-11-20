import 'dart:math';

/// RFC-4122 version 4 id. Event ids are generated on the device so retries are
/// idempotent on the server (the ingestion contract deduplicates by event id).
String newUuidV4() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  String hex(int index) => bytes[index].toRadixString(16).padLeft(2, '0');
  return '${hex(0)}${hex(1)}${hex(2)}${hex(3)}-${hex(4)}${hex(5)}-'
      '${hex(6)}${hex(7)}-${hex(8)}${hex(9)}-'
      '${hex(10)}${hex(11)}${hex(12)}${hex(13)}${hex(14)}${hex(15)}';
}

String isoUtc(DateTime value) => value.toUtc().toIso8601String();

DateTime? parseUtc(Object? value) {
  if (value is! String) return null;
  return DateTime.tryParse(value)?.toUtc();
}
