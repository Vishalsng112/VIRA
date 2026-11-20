import '../utils/ids.dart';

class DeviceInfo {
  const DeviceInfo({
    required this.deviceId,
    required this.displayName,
    required this.platform,
    required this.deviceType,
    required this.status,
    this.osVersion,
    this.clientVersion,
    this.capabilities = const [],
    this.capabilityStatus = const {},
    this.isServerLocal = false,
    this.lastSeenAt,
    this.accessRole,
  });

  final String deviceId;
  final String displayName;
  final String platform;
  final String deviceType;
  final String status;
  final String? osVersion;
  final String? clientVersion;
  final List<String> capabilities;
  final Map<String, String> capabilityStatus;
  final bool isServerLocal;
  final DateTime? lastSeenAt;
  final String? accessRole;

  bool get isActive => status == 'active';
  bool get isCurrent => false;

  factory DeviceInfo.fromJson(Map<String, dynamic> json) {
    final rawStatus = json['capability_status'];
    return DeviceInfo(
      deviceId: (json['device_id'] ?? json['id'] ?? '').toString(),
      displayName: (json['display_name'] ?? 'Device').toString(),
      platform: (json['platform'] ?? 'other').toString(),
      deviceType: (json['device_type'] ?? 'other').toString(),
      status: (json['status'] ?? 'pending').toString(),
      osVersion: json['os_version']?.toString(),
      clientVersion: json['client_version']?.toString(),
      capabilities: ((json['capabilities'] as List?) ?? const [])
          .map((item) => item.toString())
          .toList(),
      capabilityStatus: rawStatus is Map
          ? rawStatus.map(
              (key, value) => MapEntry(key.toString(), value.toString()),
            )
          : const {},
      isServerLocal: json['is_server_local'] == true,
      lastSeenAt: parseUtc(json['last_seen_at']),
      accessRole: json['access_role']?.toString(),
    );
  }
}

class DeviceProfile {
  const DeviceProfile({
    required this.platform,
    required this.deviceType,
    required this.osVersion,
    required this.hostname,
  });

  final String platform;
  final String deviceType;
  final String osVersion;
  final String hostname;
}
