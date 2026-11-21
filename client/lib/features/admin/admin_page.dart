import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/layout.dart';
import '../../app/widgets.dart';
import '../../data/api/vira_api.dart';
import '../../data/storage/outbox_store.dart';
import '../shell/app_shell.dart';

class AdminPage extends StatefulWidget {
  const AdminPage({super.key});

  @override
  State<AdminPage> createState() => _AdminPageState();
}

class _AdminPageState extends State<AdminPage>
    with SingleTickerProviderStateMixin {
  late final AppController _controller;
  late final TabController _tabs;
  bool _loading = true;
  String? _error;
  bool _reachable = false;
  Map<String, String> _sectionErrors = const {};
  Map<String, dynamic> _health = const {};
  Map<String, dynamic> _metrics = const {};
  Map<String, dynamic> _orchestration = const {};
  Map<String, dynamic> _agents = const {};
  Map<String, dynamic> _eventLag = const {};
  Map<String, dynamic> _insightFleet = const {};
  List<Map<String, dynamic>> _users = const [];
  List<Map<String, dynamic>> _devices = const [];
  List<Map<String, dynamic>> _audit = const [];
  List<Map<String, dynamic>> _sensors = const [];
  Map<String, dynamic> _jobStats = const {};
  List<Map<String, dynamic>> _jobs = const [];
  List<String> _backups = const [];
  List<Map<String, dynamic>> _alerts = const [];

  @override
  void initState() {
    super.initState();
    _controller = AppScope.of(context, listen: false);
    _tabs = TabController(length: 5, vsync: this);
    _load();
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final api = _controller.api;
    if (api == null) {
      setState(() {
        _loading = false;
        _reachable = false;
        _error = 'This device is not connected to a VIRA server.';
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
      _sectionErrors = const {};
    });

    // Re-check the account first. A cached role can be stale after the server
    // changes an account, and that used to make the whole panel look "dead".
    if (!_controller.isAdmin) {
      try {
        await _controller.refreshIdentity();
      } on ViraApiException catch (error) {
        setState(() {
          _loading = false;
          _reachable = false;
          _error = _explain(error);
        });
        return;
      } on Object catch (error) {
        setState(() {
          _loading = false;
          _reachable = false;
          _error = error.toString();
        });
        return;
      }
      if (!_controller.isAdmin) {
        setState(() {
          _loading = false;
          _reachable = false;
          _error = 'This account is not an administrator. Sign in with an admin account to manage the server.';
        });
        return;
      }
    }

    final errors = <String, String>{};
    var reachable = false;
    var authFailures = 0;

    Future<void> run<T>(
      String label,
      Future<T> future,
      void Function(T value) apply,
    ) async {
      try {
        apply(await future);
        reachable = true;
      } on ViraApiException catch (error) {
        errors[label] = _explain(error);
        if (error.isTransport) return;
        if (error.isAuthFailure) authFailures += 1;
        // The server answered, so it is reachable even if this one section
        // is not available to this build.
        reachable = true;
      } on Object catch (error) {
        errors[label] = error.toString();
      }
    }

    await Future.wait<void>([
      run('Server health', api.health(), (value) => _health = value),
      run('Metrics', api.metrics(), (value) => _metrics = value),
      run('Agents', api.orchestration(), (value) => _orchestration = value),
      run('Agent list', api.agents(), (value) => _agents = value),
      run('Users', api.adminUsers(), (value) => _users = value),
      run('Devices', api.adminDevices(), (value) {
        _devices = ((value['devices'] as List?) ?? const [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
      }),
      run('Audit log', api.auditLog(), (value) {
        _audit = ((value['audit'] as List?) ?? const [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
      }),
      run('Sensors', api.sensors(), (value) {
        _sensors = ((value['sensors'] as List?) ?? const [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
      }),
      run('Event pipeline', api.eventLag(), (value) => _eventLag = value),
      run(
        'Fleet insights',
        api.insightFleet(),
        (value) => _insightFleet = value,
      ),
      run('Background jobs', api.adminJobs(), (value) {
        _jobStats = value['stats'] is Map
            ? Map<String, dynamic>.from(value['stats'] as Map)
            : const {};
        _jobs = ((value['jobs'] as List?) ?? const [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
      }),
      run('Backups', api.adminBackups(), (value) {
        _backups = ((value['backups'] as List?) ?? const [])
            .map((item) => item.toString())
            .toList();
      }),
      run('Alerts', api.alerts(), (value) {
        _alerts = ((value['alerts'] as List?) ?? const [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
      }),
    ]);

    if (!mounted) return;
    final hardFailure = errors.length == 13;
    final signedOut = errors.isNotEmpty && authFailures == errors.length;
    setState(() {
      _loading = false;
      _reachable = reachable;
      _sectionErrors = errors;
      if (hardFailure) {
        _error =
            'We could not reach your VIRA server. Make sure it is running at '
            '${_controller.serverUrl}, then try again.';
      } else if (signedOut) {
        _error = 'Your VIRA session has expired. Sign in again from Settings, then reload the admin panel.';
      } else {
        _error = null;
      }
    });
  }

  String _explain(ViraApiException error) {
    if (error.statusCode == 401) {
      return 'Your session expired. Sign in again from Settings.';
    }
    if (error.statusCode == 403) {
      return 'Administrator permission is required.';
    }
    if (error.isTransport) {
      return 'Cannot reach the server. Check that it is running and that this device has network access.';
    }
    return error.message;
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    if (!controller.isAdmin) {
      return EmptyState(
        icon: Icons.admin_panel_settings_outlined,
        title: 'Administrator access needed',
        message:
            'This account can use VIRA, but it cannot see server settings. '
            'Sign in with an administrator account to manage the server.',
        action: FilledButton.tonalIcon(
          onPressed: _loading ? null : _load,
          icon: const Icon(Icons.refresh_rounded, size: 18),
          label: Text(_loading ? 'Checking…' : 'Check access again'),
        ),
      );
    }
    final theme = Theme.of(context);
    final healthy = (_health['status'] ?? 'unknown').toString() == 'healthy';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: EdgeInsets.fromLTRB(
            ViraLayout.pagePadding(context),
            14,
            ViraLayout.pagePadding(context),
            10,
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Server control',
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      _loading
                          ? 'Contacting ${controller.serverUrl}…'
                          : _reachable
                          ? 'Connected to ${controller.serverUrl}'
                          : 'Cannot reach ${controller.serverUrl}',
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: _reachable || _loading
                            ? theme.colorScheme.onSurfaceVariant
                            : theme.colorScheme.error,
                      ),
                    ),
                  ],
                ),
              ),
              StatusPill(
                label: _loading
                    ? 'Connecting'
                    : !_reachable
                    ? 'Offline'
                    : healthy
                    ? 'Healthy'
                    : 'Attention',
                tone: _loading
                    ? StatusTone.info
                    : !_reachable
                    ? StatusTone.error
                    : healthy
                    ? StatusTone.success
                    : StatusTone.warning,
                icon: _loading
                    ? Icons.sync
                    : !_reachable
                    ? Icons.cloud_off
                    : healthy
                    ? Icons.check_circle
                    : Icons.monitor_heart,
              ),
              const SizedBox(width: 8),
              IconButton(
                tooltip: 'Refresh admin data',
                onPressed: _loading ? null : _load,
                icon: _loading
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.refresh),
              ),
            ],
          ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 10),
            child: Card(
              color: theme.colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        _error!,
                        style: TextStyle(
                          color: theme.colorScheme.onErrorContainer,
                        ),
                      ),
                    ),
                    TextButton(onPressed: _load, child: const Text('Retry')),
                    IconButton(
                      tooltip: 'Connection settings',
                      onPressed: () =>
                          ShellNavigation.maybeOf(context)
                              ?.openModule('settings'),
                      icon: const Icon(Icons.settings_outlined, size: 20),
                    ),
                  ],
                ),
              ),
            ),
          ),
        if (_error == null && _sectionErrors.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 10),
            child: Card(
              color: theme.colorScheme.tertiaryContainer.withValues(alpha: 0.5),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(
                          Icons.info_outline,
                          size: 18,
                          color: theme.colorScheme.onTertiaryContainer,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Connected, but some sections could not load',
                            style: TextStyle(
                              color: theme.colorScheme.onTertiaryContainer,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                        TextButton(
                          onPressed: _load,
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                    for (final entry in _sectionErrors.entries.take(4))
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text(
                          '${entry.key}: ${entry.value}',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onTertiaryContainer,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        TabBar(
          controller: _tabs,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: const [
            Tab(icon: Icon(Icons.monitor_heart_outlined), text: 'Server'),
            Tab(icon: Icon(Icons.smart_toy_outlined), text: 'Agents'),
            Tab(icon: Icon(Icons.people_outline), text: 'Users'),
            Tab(icon: Icon(Icons.devices_other_outlined), text: 'Fleet'),
            Tab(icon: Icon(Icons.history), text: 'Audit'),
          ],
        ),
        const Divider(height: 1),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : TabBarView(
                  controller: _tabs,
                  children: [
                    _serverTab(theme),
                    _agentsTab(theme),
                    _usersTab(theme),
                    _devicesTab(theme),
                    _auditTab(theme),
                  ],
                ),
        ),
      ],
    );
  }

  Widget _serverTab(ThemeData theme) {
    final agents = (_orchestration['agents'] as List?) ?? const [];
    final tools = (_orchestration['tools'] as Map?) ?? const {};
    final scheduler = (_orchestration['scheduler'] as Map?) ?? const {};
    final routerInfo = (_orchestration['router'] as Map?) ?? const {};
    final uptime = (_metrics['uptime_seconds'] as num?)?.toInt() ?? 0;
    final byStatus = (_insightFleet['by_status'] as Map?) ?? const {};
    final cards = [
      StatCard(
        icon: Icons.dns_outlined,
        label: 'Server',
        value: (_health['status'] ?? 'unknown').toString(),
        caption: healthyLabel(_health),
      ),
      StatCard(
        icon: Icons.timer_outlined,
        label: 'Uptime',
        value: _duration(uptime),
        caption: 'Kernel process',
      ),
      StatCard(
        icon: Icons.smart_toy_outlined,
        label: 'Agents',
        value: '${agents.length}',
        caption: 'Loaded in registry',
      ),
      StatCard(
        icon: Icons.play_circle_outline,
        label: 'Running tasks',
        value: '${(scheduler['running_tasks'] as num?)?.toInt() ?? 0}',
        caption: 'Scheduler',
      ),
      StatCard(
        icon: Icons.build_outlined,
        label: 'Tools',
        value: '${(tools['total'] as num?)?.toInt() ?? 0}',
        caption:
            '${(tools['mcp_connections'] as num?)?.toInt() ?? 0} MCP connections',
      ),
      StatCard(
        icon: Icons.devices_other_outlined,
        label: 'Devices',
        value: '${_devices.length}',
        caption: 'Fleet inventory',
      ),
      StatCard(
        icon: Icons.people_outline,
        label: 'Users',
        value: '${_users.length}',
        caption: 'Accounts',
      ),
      StatCard(
        icon: Icons.route_outlined,
        label: 'Event router',
        value: routerInfo['running'] == true ? 'Running' : 'Stopped',
        caption: routerInfo['subscribed'] == true
            ? 'Subscribed'
            : 'Not subscribed',
      ),
    ];
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        _statGrid(cards),
        if (_alerts.isNotEmpty) ...[
          const SizedBox(height: 16),
          SectionCard(
            title: 'Alerts',
            subtitle: 'Operational issues that need attention.',
            child: Column(
              children: [
                for (final alert in _alerts)
                  ListTile(
                    leading: Icon(
                      alert['level'] == 'error'
                          ? Icons.error_outline
                          : Icons.warning_amber_outlined,
                      color: alert['level'] == 'error'
                          ? theme.colorScheme.error
                          : const Color(0xFFB06000),
                    ),
                    title: Text((alert['kind'] ?? 'alert').toString()),
                    subtitle: Text((alert['message'] ?? '').toString()),
                  ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 16),
        SectionCard(
          title: 'Health checks',
          subtitle: 'Kernel, services and subsystem status.',
          child: Column(
            children: [
              for (final entry in _health.entries.take(12))
                InfoRow(label: entry.key, value: _value(entry.value)),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Event pipeline',
          subtitle: 'Queue and outbox health.',
          child: Column(
            children: [
              InfoRow(
                label: 'Pending events',
                value: '${_eventLag['pending_events'] ?? 0}',
                icon: Icons.inbox_outlined,
              ),
              InfoRow(
                label: 'Capacity',
                value: '${_eventLag['capacity'] ?? 0}',
                icon: Icons.storage_outlined,
              ),
              InfoRow(
                label: 'Utilization',
                value:
                    '${((_eventLag['utilization'] as num?)?.toDouble() ?? 0) * 100 ~/ 1}%',
                icon: Icons.speed,
              ),
              InfoRow(
                label: 'Outbox',
                value: _value(_eventLag['outbox']),
                icon: Icons.outbox_outlined,
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Fleet status',
          subtitle: 'Devices by state.',
          child: byStatus.isEmpty
              ? const Text('No fleet data yet.')
              : Column(
                  children: [
                    for (final entry in byStatus.entries)
                      InfoRow(label: entry.key, value: '${entry.value}'),
                  ],
                ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Background jobs',
          subtitle: 'Durable worker queue.',
          child: Column(
            children: [
              for (final entry in _jobStats.entries)
                InfoRow(label: entry.key, value: '${entry.value}'),
              if (_jobs.isNotEmpty) ...[
                const Divider(height: 20),
                for (final job in _jobs.take(8))
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    dense: true,
                    title: Text((job['kind'] ?? 'job').toString()),
                    subtitle: Text(
                      '${job['status']} · attempts ${job['attempts']}'
                      '${job['last_error'] == null ? '' : ' · ${job['last_error']}'}',
                    ),
                    trailing:
                        job['status'] == 'dead' || job['status'] == 'failed'
                        ? TextButton(
                            onPressed: () async {
                              await _controller.api?.retryJob(
                                (job['id'] ?? '').toString(),
                              );
                              await _load();
                            },
                            child: const Text('Retry'),
                          )
                        : null,
                  ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Backups',
          subtitle: 'Local database snapshots.',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_backups.isEmpty)
                const Text('No backups yet.')
              else
                for (final backup in _backups.take(5))
                  Text(backup, style: theme.textTheme.bodySmall),
              const SizedBox(height: 10),
              FilledButton.tonalIcon(
                onPressed: () async {
                  await _controller.api?.createBackup();
                  await _load();
                },
                icon: const Icon(Icons.backup_outlined),
                label: const Text('Back up now'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Sensors',
          subtitle: 'Server-side sensor health.',
          child: _sensors.isEmpty
              ? const Text('No sensors reported.')
              : Column(
                  children: [
                    for (final sensor in _sensors)
                      InfoRow(
                        label: (sensor['name'] ?? 'sensor').toString(),
                        value:
                            (sensor['status'] ?? sensor['running'] ?? 'unknown')
                                .toString(),
                        icon: Icons.sensors,
                      ),
                  ],
                ),
        ),
        const SizedBox(height: 24),
      ],
    );
  }

  Widget _agentsTab(ThemeData theme) {
    final loaded = (_agents['loaded'] as List?) ?? const [];
    final persisted = (_agents['agents'] as List?) ?? const [];
    final rows = loaded.isNotEmpty ? loaded : persisted;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          children: [
            Expanded(
              child: SectionCard(
                title: 'Registered agents',
                subtitle:
                    '${rows.length} agent(s), ${loaded.length} loaded now.',
                child: const SizedBox.shrink(),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (rows.isEmpty)
          const EmptyState(
            icon: Icons.smart_toy_outlined,
            title: 'No agents',
            message: 'No agents are registered on this VIRA server.',
          )
        else
          for (final item in rows.whereType<Map>())
            _agentCard(theme, Map<String, dynamic>.from(item)),
      ],
    );
  }

  Widget _agentCard(ThemeData theme, Map<String, dynamic> agent) {
    final id = (agent['id'] ?? agent['agent_id'] ?? '').toString();
    final enabled = agent['enabled'] != false;
    final capabilities = (agent['capabilities'] as List?) ?? const [];
    final events = (agent['subscribed_events'] as List?) ?? const [];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          (agent['name'] ?? 'Agent').toString(),
                          style: theme.textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        Text(
                          '${agent['state'] ?? 'persisted'} · ${agent['version'] ?? '1.0.0'}',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                  StatusPill(
                    label: enabled ? 'Enabled' : 'Disabled',
                    tone: enabled ? StatusTone.success : StatusTone.neutral,
                  ),
                  Switch(
                    value: enabled,
                    onChanged: (value) => _setAgentEnabled(id, value),
                  ),
                  IconButton(
                    tooltip: 'Unregister agent',
                    onPressed: id.isEmpty ? null : () => _unregisterAgent(id),
                    icon: const Icon(Icons.delete_outline),
                  ),
                ],
              ),
              if ((agent['description'] ?? '').toString().isNotEmpty) ...[
                const SizedBox(height: 8),
                Text((agent['description'] ?? '').toString()),
              ],
              if (capabilities.isNotEmpty) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final capability in capabilities.whereType<Map>())
                      Chip(
                        label: Text(
                          (capability['name'] ?? 'capability').toString(),
                        ),
                        visualDensity: VisualDensity.compact,
                      ),
                  ],
                ),
              ],
              if (events.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  'Events: ${events.map((e) => e.toString()).join(', ')}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _setAgentEnabled(String id, bool enabled) async {
    final api = _controller.api;
    if (api == null) return;
    try {
      await api.setAgentEnabled(id, enabled);
      await _load();
    } on ViraApiException catch (error) {
      _snack(error.message);
    }
  }

  Future<void> _unregisterAgent(String id) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Unregister agent?'),
        content: const Text(
          'The agent definition and runtime instance are removed.',
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
            child: const Text('Unregister'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _controller.api?.unregisterAgent(id);
      await _load();
    } on ViraApiException catch (error) {
      _snack(error.message);
    }
  }

  Widget _usersTab(ThemeData theme) => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              '${_users.length} account(s)',
              style: theme.textTheme.titleMedium,
            ),
          ),
          FilledButton.icon(
            onPressed: _showCreateUser,
            icon: const Icon(Icons.person_add_alt_outlined),
            label: const Text('Add user'),
          ),
        ],
      ),
      const SizedBox(height: 12),
      for (final user in _users) _userCard(theme, user),
    ],
  );

  Widget _userCard(ThemeData theme, Map<String, dynamic> user) {
    final role = (user['role'] ?? 'user').toString();
    final status = (user['status'] ?? 'active').toString();
    final deleted = status == 'deleted';
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: ListTile(
          leading: CircleAvatar(
            child: Text(
              ((user['username'] ?? '?').toString().isEmpty
                  ? '?'
                  : (user['username'] as String)[0].toUpperCase()),
            ),
          ),
          title: Text((user['username'] ?? 'Unknown').toString()),
          subtitle: Text(
            '$role · ${user['user_id'] ?? ''}\n'
            'Created ${_when(user['created_at'])}',
          ),
          isThreeLine: true,
          trailing: PopupMenuButton<String>(
            enabled: !deleted,
            onSelected: (value) {
              if (value == 'promote') _updateUser(user, role: 'admin');
              if (value == 'demote') _updateUser(user, role: 'user');
              if (value == 'enable') _updateUser(user, status: 'active');
              if (value == 'disable') _updateUser(user, status: 'disabled');
              if (value == 'delete') _deleteUser(user);
            },
            itemBuilder: (context) => [
              if (role != 'admin')
                const PopupMenuItem(
                  value: 'promote',
                  child: Text('Make administrator'),
                ),
              if (role != 'user')
                const PopupMenuItem(value: 'demote', child: Text('Make user')),
              if (status != 'active')
                const PopupMenuItem(
                  value: 'enable',
                  child: Text('Enable account'),
                ),
              if (status == 'active')
                const PopupMenuItem(
                  value: 'disable',
                  child: Text('Disable account'),
                ),
              PopupMenuItem(
                value: 'delete',
                child: Text(
                  'Delete account',
                  style: TextStyle(color: theme.colorScheme.error),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _showCreateUser() async {
    final username = TextEditingController();
    final password = TextEditingController();
    var role = 'user';
    String? error;
    var busy = false;
    final created = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (dialogContext, setDialogState) => AlertDialog(
          title: const Text('Add user'),
          content: SizedBox(
            width: 420,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextField(
                    controller: username,
                    decoration: const InputDecoration(labelText: 'Username'),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: role,
                    decoration: const InputDecoration(labelText: 'Role'),
                    items: const [
                      DropdownMenuItem(value: 'user', child: Text('User')),
                      DropdownMenuItem(
                        value: 'admin',
                        child: Text('Administrator'),
                      ),
                    ],
                    onChanged: (value) =>
                        setDialogState(() => role = value ?? 'user'),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: password,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'Password (optional)',
                      helperText:
                          'Leave empty to generate a temporary password.',
                    ),
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
            ),
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
                      try {
                        final result = await _controller.api!.createAdminUser(
                          username: username.text.trim(),
                          role: role,
                          password: password.text,
                        );
                        if (dialogContext.mounted) {
                          Navigator.pop(dialogContext, result);
                        }
                      } on ViraApiException catch (exception) {
                        setDialogState(() {
                          busy = false;
                          error = exception.message;
                        });
                      } on Object catch (exception) {
                        setDialogState(() {
                          busy = false;
                          error = exception.toString();
                        });
                      }
                    },
              child: Text(busy ? 'Creating…' : 'Create user'),
            ),
          ],
        ),
      ),
    );
    // The dialog route may still be animating out; let the controllers be
    // collected instead of disposing them while a TextField still references them.
    if (created == null || !mounted) return;
    await _showCreatedCredentials(created);
    await _load();
  }

  Future<void> _showCreatedCredentials(Map<String, dynamic> result) async {
    final temp = result['temporary_password'];
    final recovery = result['recovery_code'];
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('User created'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Username: ${result['username'] ?? ''}'),
              if (temp != null) ...[
                const SizedBox(height: 12),
                const Text('Temporary password (shown once):'),
                SelectableText(
                  temp.toString(),
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ],
              if (recovery != null) ...[
                const SizedBox(height: 12),
                const Text('Recovery code (shown once):'),
                SelectableText(
                  recovery.toString(),
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
              ],
            ],
          ),
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Done'),
          ),
        ],
      ),
    );
  }

  Future<void> _updateUser(
    Map<String, dynamic> user, {
    String? role,
    String? status,
  }) async {
    try {
      await _controller.api?.updateAdminUser(
        (user['user_id'] ?? '').toString(),
        role: role,
        status: status,
      );
      await _load();
    } on ViraApiException catch (error) {
      _snack(error.message);
    }
  }

  Future<void> _deleteUser(Map<String, dynamic> user) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete ${user['username']}?'),
        content: const Text(
          'The account is soft-deleted and its sessions are revoked. This cannot be undone from this panel.',
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
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _controller.api?.deleteAdminUser(
        (user['user_id'] ?? '').toString(),
      );
      await _load();
    } on ViraApiException catch (error) {
      _snack(error.message);
    }
  }

  Widget _devicesTab(ThemeData theme) {
    final batteryByDevice = <String, Map<String, dynamic>>{};
    final fleet = (_insightFleet['devices'] as List?) ?? const [];
    for (final item in fleet.whereType<Map>()) {
      batteryByDevice[item['id']?.toString() ?? ''] = Map<String, dynamic>.from(
        item,
      );
    }
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          '${_devices.length} device(s) in the fleet',
          style: theme.textTheme.titleMedium,
        ),
        const SizedBox(height: 12),
        if (_devices.isEmpty)
          const EmptyState(
            icon: Icons.devices_other_outlined,
            title: 'No devices',
            message: 'No endpoint devices are registered yet.',
          )
        else
          for (final device in _devices)
            _deviceCard(
              theme,
              device,
              batteryByDevice[(device['device_id'] ?? '').toString()],
            ),
      ],
    );
  }

  Widget _deviceCard(
    ThemeData theme,
    Map<String, dynamic> device,
    Map<String, dynamic>? insight,
  ) {
    final status = (device['status'] ?? 'unknown').toString();
    final health = (device['health'] as Map?) ?? const {};
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      (device['display_name'] ?? 'Device').toString(),
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  StatusPill(
                    label: status,
                    tone: status == 'active'
                        ? StatusTone.success
                        : status == 'pending'
                        ? StatusTone.warning
                        : StatusTone.error,
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                '${device['platform'] ?? ''} · ${device['device_type'] ?? ''}'
                '${device['is_server_local'] == true ? ' · server-local' : ''}',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 16,
                runSpacing: 6,
                children: [
                  _metric('Last seen', _when(device['last_seen_at'])),
                  _metric('Queue', '${health['queue_backlog'] ?? 0}'),
                  _metric(
                    'Events',
                    health['last_event_at'] == null
                        ? '—'
                        : _when(health['last_event_at']),
                  ),
                  if (insight?['battery_level'] != null)
                    _metric(
                      'Battery',
                      '${insight!['battery_level']}%${insight['charging'] == true ? ' ⚡' : ''}',
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _auditTab(ThemeData theme) => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      Text(
        'Recent security and admin activity',
        style: theme.textTheme.titleMedium,
      ),
      const SizedBox(height: 12),
      if (_audit.isEmpty)
        const EmptyState(
          icon: Icons.history,
          title: 'No audit entries',
          message: 'Authentication, admin and device actions appear here.',
        )
      else
        for (final entry in _audit.take(100))
          Card(
            child: ListTile(
              leading: Icon(
                entry['allowed'] == 1 || entry['allowed'] == true
                    ? Icons.check_circle_outline
                    : Icons.block,
                color: entry['allowed'] == 1 || entry['allowed'] == true
                    ? const Color(0xFF137333)
                    : theme.colorScheme.error,
              ),
              title: Text(
                '${entry['event_type'] ?? 'event'} · ${entry['action'] ?? ''}',
              ),
              subtitle: Text(
                '${_when(entry['created_at'] ?? entry['timestamp'])}'
                '${entry['target'] == null ? '' : ' · ${entry['target']}'}'
                '${entry['details'] == null ? '' : ' · ${entry['details']}'}',
              ),
            ),
          ),
    ],
  );

  Widget _statGrid(List<Widget> cards) => LayoutBuilder(
    builder: (context, constraints) {
      const spacing = 12.0;
      final columns = constraints.maxWidth >= 1000
          ? 4
          : constraints.maxWidth >= 600
          ? 3
          : constraints.maxWidth >= 360
          ? 2
          : 1;
      final width = (constraints.maxWidth - spacing * (columns - 1)) / columns;
      return Wrap(
        spacing: spacing,
        runSpacing: spacing,
        children: [
          for (final card in cards) SizedBox(width: width, child: card),
        ],
      );
    },
  );

  Widget _metric(String label, String value) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        label,
        style: Theme.of(context).textTheme.bodySmall
            ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant),
      ),
      Text(
        value,
        style: Theme.of(context).textTheme.bodyMedium
            ?.copyWith(fontWeight: FontWeight.w600),
      ),
    ],
  );

  String _value(Object? value) {
    if (value is Map) {
      return value.entries.map((e) => '${e.key}=${e.value}').join(', ');
    }
    if (value is List) return value.join(', ');
    return value?.toString() ?? '—';
  }

  String _when(Object? value) {
    if (value == null) return 'Never';
    final text = value.toString();
    final parsed = DateTime.tryParse(text);
    if (parsed == null) return text;
    return OutboxStore.prettyTime(parsed);
  }

  String _duration(int seconds) {
    if (seconds <= 0) return '0m';
    final hours = seconds ~/ 3600;
    final minutes = (seconds % 3600) ~/ 60;
    return hours > 0 ? '${hours}h ${minutes}m' : '${minutes}m';
  }

  String healthyLabel(Map<String, dynamic> health) {
    final status = health['status']?.toString() ?? 'unknown';
    return status == 'healthy' ? 'All systems nominal' : 'Check health details';
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }
}
