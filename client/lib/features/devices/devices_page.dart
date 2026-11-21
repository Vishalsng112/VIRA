import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/layout.dart';
import '../../app/widgets.dart';
import '../../core/models/device_info.dart';
import '../../data/storage/outbox_store.dart';

class DevicesPage extends StatefulWidget {
  const DevicesPage({super.key});

  @override
  State<DevicesPage> createState() => _DevicesPageState();
}

class _DevicesPageState extends State<DevicesPage> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) AppScope.of(context, listen: false).refreshDevices();
    });
  }

  Future<void> _rename(AppController controller, DeviceInfo device) async {
    final text = TextEditingController(text: device.displayName);
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rename device'),
        content: TextField(
          controller: text,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Device name'),
          onSubmitted: (value) => Navigator.pop(context, value),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, text.text),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (name == null || !mounted) return;
    final error = await controller.renameDevice(device.deviceId, name);
    if (error != null && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
    }
  }

  Future<void> _revoke(AppController controller, DeviceInfo device) async {
    final current = device.deviceId == controller.deviceId;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(current ? 'Unlink this device?' : 'Revoke device?'),
        content: Text(
          current
              ? 'This device will lose access immediately. Local credentials and queued events will be deleted.'
              : '${device.displayName} will no longer be able to send events. This cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
            ),
            child: Text(current ? 'Unlink' : 'Revoke'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final error = await controller.revokeDevice(device.deviceId);
    if (error != null && mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final theme = Theme.of(context);
    final devices = controller.devices;
    return RefreshIndicator(
      onRefresh: controller.refreshDevices,
      child: ListView(
        padding: ViraLayout.pageInsets(context),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 980),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'Devices',
                              style: theme.textTheme.headlineSmall?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              'Devices linked to your VIRA account.',
                              style: theme.textTheme.bodyMedium?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: 'Refresh',
                        onPressed: controller.refreshDevices,
                        icon: const Icon(Icons.refresh),
                      ),
                    ],
                  ),
                  if (controller.devicesError != null) ...[
                    const SizedBox(height: 12),
                    Card(
                      color: theme.colorScheme.errorContainer,
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Text(
                          controller.devicesError!,
                          style: TextStyle(
                            color: theme.colorScheme.onErrorContainer,
                          ),
                        ),
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  if (devices.isEmpty)
                    const EmptyState(
                      icon: Icons.devices_other,
                      title: 'No devices listed',
                      message: 'Pull to refresh. If your session expired, reconnect this device from Settings.',
                    )
                  else
                    ...devices.map(
                      (device) => Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: _DeviceCard(
                          device: device,
                          current: device.deviceId == controller.deviceId,
                          onRename: () => _rename(controller, device),
                          onRevoke: () => _revoke(controller, device),
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DeviceCard extends StatelessWidget {
  const _DeviceCard({
    required this.device,
    required this.current,
    required this.onRename,
    required this.onRevoke,
  });

  final DeviceInfo device;
  final bool current;
  final VoidCallback onRename;
  final VoidCallback onRevoke;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final revoked = device.status == 'revoked' || device.status == 'retired';
    final (tone, label) = switch (device.status) {
      'active' => (StatusTone.success, 'Active'),
      'pending' => (StatusTone.warning, 'Pending'),
      'revoked' => (StatusTone.error, 'Revoked'),
      'retired' => (StatusTone.neutral, 'Retired'),
      _ => (StatusTone.neutral, device.status),
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: current
                    ? theme.colorScheme.primaryContainer
                    : theme.colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Icon(
                _platformIcon(device.platform),
                color: current
                    ? theme.colorScheme.onPrimaryContainer
                    : theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    spacing: 8,
                    runSpacing: 4,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(
                        device.displayName,
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      if (current)
                        const StatusPill(
                          label: 'This device',
                          tone: StatusTone.info,
                          icon: Icons.check,
                        ),
                      StatusPill(label: label, tone: tone),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${device.platform} · ${device.deviceType}'
                    '${device.osVersion == null ? '' : ' · ${device.osVersion}'}',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'Last seen ${OutboxStore.prettyTime(device.lastSeenAt)}',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            PopupMenuButton<String>(
              enabled: !revoked,
              onSelected: (value) {
                if (value == 'rename') onRename();
                if (value == 'revoke') onRevoke();
              },
              itemBuilder: (context) => [
                const PopupMenuItem(
                  value: 'rename',
                  child: ListTile(
                    leading: Icon(Icons.edit_outlined),
                    title: Text('Rename'),
                  ),
                ),
                PopupMenuItem(
                  value: 'revoke',
                  child: ListTile(
                    leading: Icon(
                      Icons.remove_circle_outline,
                      color: theme.colorScheme.error,
                    ),
                    title: Text(
                      'Revoke',
                      style: TextStyle(color: theme.colorScheme.error),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  IconData _platformIcon(String platform) => switch (platform) {
    'android' => Icons.phone_android,
    'ios' => Icons.phone_iphone,
    'windows' => Icons.desktop_windows_outlined,
    'macos' => Icons.laptop_mac,
    'linux' => Icons.computer,
    'web' => Icons.language,
    _ => Icons.devices_other,
  };
}
