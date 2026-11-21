import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/layout.dart';
import '../../app/widgets.dart';
import '../../core/config/app_config.dart';
import '../../data/storage/outbox_store.dart';
import '../../services/notifications/notification_hub.dart';
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
      padding: ViraLayout.pageInsets(context),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 920),
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
                            onPressed: () =>
                                _reauthenticate(context, controller),
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
                  title: 'Appearance',
                  subtitle: 'Choose light, dark or follow the system setting. Your choice is remembered on this device.',
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      SegmentedButton<AppThemeMode>(
                        segments: const [
                          ButtonSegment(
                            value: AppThemeMode.system,
                            icon: Icon(Icons.brightness_auto_rounded),
                            label: Text('System'),
                          ),
                          ButtonSegment(
                            value: AppThemeMode.light,
                            icon: Icon(Icons.light_mode_outlined),
                            label: Text('Light'),
                          ),
                          ButtonSegment(
                            value: AppThemeMode.dark,
                            icon: Icon(Icons.dark_mode_outlined),
                            label: Text('Dark'),
                          ),
                        ],
                        selected: {controller.themeMode},
                        onSelectionChanged: (value) =>
                            controller.setThemeMode(value.first),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'The glass cards, gradients and status colours adapt automatically.',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Permissions and notifications',
                  subtitle: 'Only the signals you enable are captured. Some also need an OS permission.',
                  child: Column(
                    children: [
                      for (final state in controller.collectors)
                        if (state.enabled &&
                            state.status == 'permission_denied')
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            leading: const Icon(Icons.lock_outline),
                            title: Text(state.collector.title),
                            subtitle: const Text(
                              'Needs an operating-system permission.',
                            ),
                            trailing: TextButton(
                              onPressed: () async {
                                final opened = await controller
                                    .requestCollectorAccess(state.collector.id);
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(
                                    content: Text(
                                      opened
                                          ? 'Opened the permission settings.'
                                          : 'This platform opens permissions from the Overview page.',
                                    ),
                                  ),
                                );
                              },
                              child: const Text('Allow'),
                            ),
                          ),
                      if (!kIsWeb &&
                          defaultTargetPlatform == TargetPlatform.android)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.insights_outlined),
                          title: const Text('Activity insights access'),
                          subtitle: Text(
                            controller.isSideloaded
                                ? 'Controls app usage and screen time. If Android '
                                      'greys out the switch, open App info → ⋮ → '
                                      'Allow restricted settings.'
                                : 'Controls app usage and screen time. Android '
                                      'requires Usage Access for these signals.',
                          ),
                          trailing: TextButton(
                            onPressed: () async {
                              final opened = await controller
                                  .requestCollectorAccess(collectorAppUsage);
                              if (!context.mounted) return;
                              if (!opened) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                    content: Text(
                                      'Android did not open the Usage Access settings page.',
                                    ),
                                  ),
                                );
                              }
                            },
                            child: const Text('Open settings'),
                          ),
                        ),
                      if (!kIsWeb &&
                          defaultTargetPlatform == TargetPlatform.android)
                        const Divider(height: 20),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('In-app break reminders'),
                        subtitle: const Text(
                          'Show gentle break suggestions in Insights during long sessions.',
                        ),
                        value: controller.breakRemindersEnabled,
                        onChanged: controller.setBreakRemindersEnabled,
                      ),
                      const Divider(height: 20),
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(
                          Icons.notifications_active_outlined,
                        ),
                        title: const Text('Agent notifications'),
                        subtitle: const Text(
                          'Show native alerts for scheduled agent results while '
                          'VIRA Link is running. Android asks for notification '
                          'permission during first-run setup.',
                        ),
                        trailing: TextButton(
                          onPressed: () async {
                            final granted = await NotificationHub.instance
                                .requestPermission(controller: controller);
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                content: Text(
                                  granted
                                      ? 'Native agent notifications are enabled.'
                                      : 'Notification permission was not granted. Enable it in Android app settings.',
                                ),
                              ),
                            );
                          },
                          child: const Text('Enable'),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Sync',
                  subtitle: 'The outbox drains automatically while the VIRA server is reachable.',
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
                  title: 'Privacy and data',
                  subtitle: 'Local data stays on this device unless you export or sync it.',
                  child: Column(
                    children: [
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.download_outlined),
                        title: const Text('Export local data'),
                        subtitle: const Text(
                          'Copy a JSON snapshot of local insights, settings and the outbox. Credentials are never included.',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _exportLocalData(context, controller),
                      ),
                      const Divider(height: 1),
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          Icons.delete_sweep_outlined,
                          color: theme.colorScheme.error,
                        ),
                        title: Text(
                          'Clear local insights',
                          style: TextStyle(color: theme.colorScheme.error),
                        ),
                        subtitle: const Text(
                          'Delete the local app-usage and screen-session ledgers. Queued events are not affected.',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _clearLocalInsights(context, controller),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Diagnostics',
                  subtitle: 'Off by default. Diagnostics stay on this device unless you choose to send them.',
                  child: Column(
                    children: [
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        title: const Text('Record anonymous diagnostics'),
                        subtitle: const Text(
                          'Stores recent app errors with the platform, sync state and '
                          'collector status. Credentials, server URL, device ID, '
                          'username and message content are never included.',
                        ),
                        value: controller.diagnosticsEnabled,
                        onChanged: controller.setDiagnosticsEnabled,
                      ),
                      const Divider(height: 20),
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.copy_all_outlined),
                        title: const Text('Copy diagnostic report'),
                        subtitle: const Text(
                          'Review the redacted report before sharing it.',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _copyDiagnosticReport(context, controller),
                      ),
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.outbox_outlined),
                        title: const Text('Send diagnostic report'),
                        subtitle: Text(
                          controller.isConnected
                              ? 'Uploads the redacted report to your VIRA server.'
                              : 'Connect to your VIRA server to send a report.',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: controller.isConnected
                            ? () => _sendDiagnosticReport(context, controller)
                            : null,
                      ),
                      if (controller.diagnosticsEnabled)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          leading: Icon(
                            Icons.delete_outline,
                            color: theme.colorScheme.error,
                          ),
                          title: Text(
                            'Clear diagnostic history',
                            style: TextStyle(color: theme.colorScheme.error),
                          ),
                          onTap: () => _clearDiagnostics(context, controller),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                SectionCard(
                  title: 'Device lifecycle',
                  subtitle:
                      'Revocation takes effect on the server immediately.',
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
    if (name == null || !context.mounted) return;
    final id = controller.deviceId;
    if (id == null) return;
    final error = await controller.renameDevice(id, name);
    if (error != null && context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error)));
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

  Future<void> _exportLocalData(
    BuildContext context,
    AppController controller,
  ) async {
    final json = await controller.exportLocalData();
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Local data export'),
        content: SizedBox(
          width: 640,
          height: 420,
          child: SingleChildScrollView(
            child: SelectableText(
              json,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Close'),
          ),
          FilledButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: json));
              if (!dialogContext.mounted) return;
              Navigator.pop(dialogContext);
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Local data copied to clipboard.'),
                  ),
                );
              }
            },
            icon: const Icon(Icons.copy_outlined),
            label: const Text('Copy JSON'),
          ),
        ],
      ),
    );
  }

  Future<void> _clearLocalInsights(
    BuildContext context,
    AppController controller,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear local insights?'),
        content: const Text(
          'This deletes app-usage and screen-session summaries stored on this device. Events already sent to the server are not affected.',
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
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    await controller.clearLocalHistory();
    if (context.mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Local insights cleared.')));
    }
  }

  Future<void> _copyDiagnosticReport(
    BuildContext context,
    AppController controller,
  ) async {
    final report = controller.diagnosticReportJson();
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Diagnostic report'),
        content: SizedBox(
          width: 640,
          height: 420,
          child: SingleChildScrollView(
            child: SelectableText(
              report,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Close'),
          ),
          FilledButton.icon(
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: report));
              if (!dialogContext.mounted) return;
              Navigator.pop(dialogContext);
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('Diagnostic report copied to clipboard.'),
                  ),
                );
              }
            },
            icon: const Icon(Icons.copy_outlined),
            label: const Text('Copy report'),
          ),
        ],
      ),
    );
  }

  Future<void> _sendDiagnosticReport(
    BuildContext context,
    AppController controller,
  ) async {
    if (!controller.diagnosticsEnabled) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Turn on anonymous diagnostics first, then send a report.',
          ),
        ),
      );
      return;
    }
    final error = await controller.sendDiagnosticReport();
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          error ??
              'Diagnostic report sent. Thank you for helping improve VIRA.',
        ),
      ),
    );
  }

  Future<void> _clearDiagnostics(
    BuildContext context,
    AppController controller,
  ) async {
    await controller.clearDiagnosticHistory();
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Diagnostic history cleared.')),
      );
    }
  }

  Future<void> _disconnect(
    BuildContext context,
    AppController controller,
    bool unlink,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          unlink ? 'Sign out and unlink?' : 'Disconnect this device?',
        ),
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
