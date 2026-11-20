import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/widgets.dart';
import '../../core/config/app_config.dart';
import '../../data/storage/outbox_store.dart';
import '../../services/sync/sync_service.dart';

class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final theme = Theme.of(context);
    final snapshot = controller.syncSnapshot;
    final device = controller.currentDevice;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 880),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text(
                  'Settings',
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'Connection, capture and device lifecycle.',
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Account and device',
                  subtitle: 'Credentials are managed by the VIRA server.',
                  child: Column(
                    children: [
                      InfoRow(
                        label: 'Account',
                        value: controller.username ?? 'Unknown',
                        icon: Icons.person_outline,
                      ),
                      InfoRow(
                        label: 'Server',
                        value: controller.serverUrl,
                        icon: Icons.dns_outlined,
                      ),
                      InfoRow(
                        label: 'Device name',
                        value:
                            device?.displayName ??
                            controller.settings.deviceName ??
                            'Unknown',
                        icon: Icons.devices_other_outlined,
                      ),
                      InfoRow(
                        label: 'Device ID',
                        value: controller.deviceId ?? 'Not enrolled',
                        icon: Icons.fingerprint,
                      ),
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 10,
                        runSpacing: 8,
                        children: [
                          OutlinedButton.icon(
                            onPressed: () => _renameDevice(context, controller),
                            icon: const Icon(Icons.edit_outlined),
                            label: const Text('Rename this device'),
                          ),
                          OutlinedButton.icon(
                            onPressed: () => _reauthenticate(context, controller),
                            icon: const Icon(Icons.lock_open_outlined),
                            label: const Text('Sign in again'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Sync',
                  subtitle:
                      'The outbox drains automatically while the VIRA server is reachable.',
                  child: Column(
                    children: [
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Automatic sync'),
                        subtitle: const Text(
                          'Retry every few seconds when the server is reachable.',
                        ),
                        value: controller.autoSync,
                        onChanged: controller.setAutoSync,
                      ),
                      const Divider(height: 24),
                      _SyncStatusRow(snapshot: snapshot),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          FilledButton.tonalIcon(
                            onPressed: controller.syncNow,
                            icon: const Icon(Icons.sync),
                            label: const Text('Sync now'),
                          ),
                          const SizedBox(width: 10),
                          OutlinedButton.icon(
                            onPressed: controller.captureNow,
                            icon: const Icon(Icons.play_arrow),
                            label: const Text('Capture now'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Capture',
                  subtitle:
                      'Individual collectors are toggled on the Overview page.',
                  child: Column(
                    children: [
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Capture on this device'),
                        subtitle: const Text(
                          'Turning this off stops new events. Queued events still sync.',
                        ),
                        value: controller.captureEnabled,
                        onChanged: controller.setCaptureEnabled,
                      ),
                      const Divider(height: 24),
                      InfoRow(
                        label: 'Pending',
                        value: '${controller.pendingCount} events',
                        icon: Icons.inventory_2_outlined,
                      ),
                      InfoRow(
                        label: 'Last sync',
                        value: OutboxStore.prettyTime(snapshot.lastSync),
                        icon: Icons.schedule,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Device lifecycle',
                  subtitle: 'Revocation takes effect on the server immediately.',
                  child: Column(
                    children: [
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.link_off),
                        title: const Text('Disconnect'),
                        subtitle: const Text(
                          'Stop syncing and remove credentials from this device. The server-side device remains for later re-enrollment.',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _disconnect(context, controller, false),
                      ),
                      const Divider(height: 1),
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          Icons.delete_forever_outlined,
                          color: theme.colorScheme.error,
                        ),
                        title: Text(
                          'Sign out and unlink',
                          style: TextStyle(color: theme.colorScheme.error),
                        ),
                        subtitle: const Text(
                          'Revoke this device on the server, clear credentials and delete the local outbox.',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _disconnect(context, controller, true),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const BrandMark(size: 40),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                '$appName $appVersion',
                                style: theme.textTheme.titleSmall?.copyWith(
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                'Protocol v$protocolVersion · device companion for a private VIRA server.',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _renameDevice(
    BuildContext context,
    AppController controller,
  ) async {
    final text = TextEditingController(
      text:
          controller.currentDevice?.displayName ??
          controller.settings.deviceName ??
          '',
    );
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rename this device'),
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
    text.dispose();
    if (name == null || !context.mounted) return;
    final id = controller.deviceId;
    if (id == null) return;
    final error = await controller.renameDevice(id, name);
    if (error != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
    }
  }

  Future<void> _reauthenticate(
    BuildContext context,
    AppController controller,
  ) async {
    final username = TextEditingController(text: controller.username ?? '');
    final password = TextEditingController();
    String? error;
    var busy = false;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: const Text('Sign in again'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: username,
                decoration: const InputDecoration(labelText: 'Username'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: password,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'Password'),
              ),
              if (error != null) ...[
                const SizedBox(height: 12),
                Text(
                  error!,
                  style: TextStyle(
                    color: Theme.of(dialogContext).colorScheme.error,
                  ),
                ),
              ],
            ],
          ),
          actions: [
            TextButton(
              onPressed: busy ? null : () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: busy
                  ? null
                  : () async {
                      setDialogState(() {
                        busy = true;
                        error = null;
                      });
                      final message = await controller.refreshSession(
                        username: username.text,
                        password: password.text,
                      );
                      if (!dialogContext.mounted) return;
                      if (message == null) {
                        Navigator.pop(dialogContext);
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text('Account session refreshed.'),
                            ),
                          );
                        }
                      } else {
                        setDialogState(() {
                          busy = false;
                          error = message;
                        });
                      }
                    },
              child: Text(busy ? 'Signing in…' : 'Sign in'),
            ),
          ],
        ),
      ),
    );
    username.dispose();
    password.dispose();
  }

  Future<void> _disconnect(
    BuildContext context,
    AppController controller,
    bool unlink,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(unlink ? 'Sign out and unlink?' : 'Disconnect this device?'),
        content: Text(
          unlink
              ? 'This revokes the device on the server, removes local credentials and deletes queued events.'
              : 'This removes local credentials and stops syncing. Queued events stay on this device until you clear them.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style: unlink
                ? FilledButton.styleFrom(
                    backgroundColor: Theme.of(context).colorScheme.error,
                  )
                : null,
            child: Text(unlink ? 'Sign out and unlink' : 'Disconnect'),
          ),
        ],
      ),
    );
    if (confirmed == true) await controller.disconnect(unlink: unlink);
  }
}

class _SyncStatusRow extends StatelessWidget {
  const _SyncStatusRow({required this.snapshot});

  final SyncSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final (label, tone, icon) = switch (snapshot.state) {
      SyncState.idle => ('Up to date', StatusTone.success, Icons.check_circle),
      SyncState.syncing => ('Syncing', StatusTone.info, Icons.sync),
      SyncState.offline => ('Offline', StatusTone.warning, Icons.cloud_off),
      SyncState.error => ('Sync issue', StatusTone.error, Icons.error_outline),
      SyncState.revoked => ('Device revoked', StatusTone.error, Icons.block),
    };
    return Row(
      children: [
        StatusPill(label: label, tone: tone, icon: icon),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            snapshot.lastError ??
                (snapshot.nextRetry == null
                    ? 'Queued events: ${snapshot.pending}'
                    : 'Next retry ${OutboxStore.prettyTime(snapshot.nextRetry)}'),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ],
    );
  }
}
