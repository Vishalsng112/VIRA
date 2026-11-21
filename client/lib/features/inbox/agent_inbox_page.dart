import 'package:material_ui/material_ui.dart';

import '../../app/app_scope.dart';
import '../../app/layout.dart';
import '../../app/widgets.dart';
import '../../core/models/agent_inbox.dart';
import '../../data/api/vira_api.dart';
import 'schedule_editor_page.dart';

enum _InboxView { notifications, schedules }

class AgentInboxPage extends StatefulWidget {
  const AgentInboxPage({super.key});

  @override
  State<AgentInboxPage> createState() => _AgentInboxPageState();
}

class _AgentInboxPageState extends State<AgentInboxPage> {
  _InboxView _view = _InboxView.notifications;
  List<AgentNotification> _notifications = const [];
  List<AgentSchedule> _schedules = const [];
  List<AgentRecipe> _recipes = const [];
  int _unread = 0;
  bool _loading = true;
  String? _error;

  ViraApi? get _api => AppScope.of(context, listen: false).api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = _api;
    if (api == null) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Connect to a VIRA server to see agent updates.';
        });
      }
      return;
    }
    try {
      final results = await Future.wait([
        api.notifications(limit: 100),
        api.agentSchedules(),
        api.unreadNotificationCount(),
        api.agentRecipes(),
      ]);
      if (!mounted) return;
      setState(() {
        _notifications = results[0] as List<AgentNotification>;
        _schedules = results[1] as List<AgentSchedule>;
        _unread = results[2] as int;
        _recipes = results[3] as List<AgentRecipe>;
        _loading = false;
        _error = null;
      });
    } on ViraApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  Future<void> _openNotification(AgentNotification item) async {
    if (!item.isRead) {
      try {
        await _api?.markNotificationRead(item.id);
      } on ViraApiException {
        // Opening the detail is still useful if marking read fails.
      }
    }
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => NotificationDetailPage(notification: item),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _runNow(AgentSchedule schedule) async {
    try {
      await _api?.runAgentSchedule(schedule.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            '${schedule.name} is queued. It will run on the next scheduler tick.',
          ),
        ),
      );
      await Future<void>.delayed(const Duration(seconds: 3));
      if (mounted) await _load();
    } on ViraApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  void _openRuns(AgentSchedule schedule) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => AgentScheduleRunsPage(schedule: schedule),
      ),
    );
  }

  AgentRecipe? _recipeFor(String agentId) {
    for (final recipe in _recipes) {
      if (recipe.agentId == agentId || recipe.id == agentId) return recipe;
    }
    return null;
  }

  Future<void> _openEditor({
    AgentRecipe? recipe,
    AgentSchedule? schedule,
  }) async {
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        builder: (_) => ScheduleEditorPage(recipe: recipe, existing: schedule),
      ),
    );
    if (changed == true && mounted) await _load();
  }

  Future<void> _toggleSchedule(AgentSchedule schedule) async {
    try {
      await _api?.updateAgentSchedule(schedule.id, {
        'enabled': !schedule.enabled,
      });
      if (mounted) await _load();
    } on ViraApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  Future<void> _deleteSchedule(AgentSchedule schedule) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete schedule?'),
        content: Text(
          'Delete "${schedule.name}"? Existing run history is removed too.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
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
      await _api?.deleteAgentSchedule(schedule.id);
      if (mounted) await _load();
    } on ViraApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  void _showScheduleMenu(AgentSchedule schedule) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Edit schedule'),
              onTap: () {
                Navigator.pop(sheetContext);
                _openEditor(
                  recipe: _recipeFor(schedule.agentId),
                  schedule: schedule,
                );
              },
            ),
            ListTile(
              leading: Icon(
                schedule.enabled
                    ? Icons.pause_circle_outline
                    : Icons.play_circle_outline,
              ),
              title: Text(
                schedule.enabled ? 'Pause schedule' : 'Resume schedule',
              ),
              onTap: () {
                Navigator.pop(sheetContext);
                _toggleSchedule(schedule);
              },
            ),
            ListTile(
              leading: Icon(
                Icons.delete_outline,
                color: Theme.of(sheetContext).colorScheme.error,
              ),
              title: Text(
                'Delete schedule',
                style: TextStyle(
                  color: Theme.of(sheetContext).colorScheme.error,
                ),
              ),
              onTap: () {
                Navigator.pop(sheetContext);
                _deleteSchedule(schedule);
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: ViraLayout.pageInsets(context),
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Agent inbox',
                      style: theme.textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Proactive agent results and the schedules behind them.',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              if (_unread > 0)
                StatusPill(
                  label: '$_unread unread',
                  tone: StatusTone.info,
                  icon: Icons.mark_email_unread_outlined,
                ),
            ],
          ),
          const SizedBox(height: 16),
          SegmentedButton<_InboxView>(
            segments: [
              ButtonSegment(
                value: _InboxView.notifications,
                icon: const Icon(Icons.inbox_outlined),
                label: Text('Inbox (${_notifications.length})'),
              ),
              ButtonSegment(
                value: _InboxView.schedules,
                icon: const Icon(Icons.schedule),
                label: Text('Schedules (${_schedules.length})'),
              ),
            ],
            selected: {_view},
            onSelectionChanged: (value) => setState(() => _view = value.first),
          ),
          const SizedBox(height: 16),
          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 60),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_error != null)
            EmptyState(
              icon: Icons.cloud_off_outlined,
              title: 'Cannot load agent updates',
              message: _error!,
              action: FilledButton(
                onPressed: _load,
                child: const Text('Retry'),
              ),
            )
          else if (_view == _InboxView.notifications)
            _notificationList(theme)
          else
            _scheduleList(theme),
        ],
      ),
    );
  }

  Widget _notificationList(ThemeData theme) {
    if (_notifications.isEmpty) {
      return const EmptyState(
        icon: Icons.notifications_none_outlined,
        title: 'No agent updates yet',
        message: 'Scheduled agents will leave their results here. Create a schedule from the dashboard or API, or run one now from the Schedules tab.',
      );
    }
    return Column(
      children: [
        for (final item in _notifications) ...[
          _NotificationTile(
            notification: item,
            onTap: () => _openNotification(item),
          ),
          const SizedBox(height: 10),
        ],
      ],
    );
  }

  Widget _scheduleList(ThemeData theme) {
    final available = _recipes.where((recipe) => recipe.available).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (available.isNotEmpty) ...[
          Text(
            'Add to your day',
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 8),
          for (final recipe in available) ...[
            _RecipeTile(
              recipe: recipe,
              onAdd: () => _openEditor(recipe: recipe),
            ),
            const SizedBox(height: 10),
          ],
          const SizedBox(height: 10),
        ],
        if (_schedules.isEmpty)
          const EmptyState(
            icon: Icons.schedule_outlined,
            title: 'No schedules yet',
            message: 'Pick an agent above, choose a time, and it will start leaving updates in your inbox.',
          )
        else
          for (final schedule in _schedules) ...[
            _ScheduleTile(
              schedule: schedule,
              onRun: () => _runNow(schedule),
              onRuns: () => _openRuns(schedule),
              onMenu: () => _showScheduleMenu(schedule),
            ),
            const SizedBox(height: 10),
          ],
      ],
    );
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.notification, required this.onTap});

  final AgentNotification notification;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final unread = !notification.isRead;
    return GlassCard(
      onTap: onTap,
      padding: const EdgeInsets.all(16),
      radius: 20,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              color: theme.colorScheme.primary.withValues(alpha: 0.12),
            ),
            child: Icon(
              notification.kind == 'agent_schedule'
                  ? Icons.auto_awesome
                  : Icons.notifications_outlined,
              color: theme.colorScheme.primary,
              size: 22,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        notification.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall?.copyWith(
                          fontWeight: unread
                              ? FontWeight.w800
                              : FontWeight.w600,
                        ),
                      ),
                    ),
                    if (unread)
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          color: theme.colorScheme.primary,
                          shape: BoxShape.circle,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  notification.body,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Text(
                      _relativeTime(notification.createdAt),
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const Spacer(),
                    Icon(
                      Icons.chevron_right,
                      size: 18,
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RecipeTile extends StatelessWidget {
  const _RecipeTile({required this.recipe, required this.onAdd});

  final AgentRecipe recipe;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return GlassCard(
      padding: const EdgeInsets.all(16),
      radius: 20,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  recipe.name,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              StatusPill(label: recipe.architecture, tone: StatusTone.info),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            recipe.pitch,
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
              height: 1.4,
            ),
          ),
          if (recipe.scheduleModes.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Modes: ${recipe.scheduleModes.join(', ')}',
              style: theme.textTheme.labelSmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
          const SizedBox(height: 10),
          Align(
            alignment: Alignment.centerRight,
            child: FilledButton.tonalIcon(
              onPressed: onAdd,
              icon: const Icon(Icons.add_alarm, size: 18),
              label: const Text('Add schedule'),
            ),
          ),
        ],
      ),
    );
  }
}

class _ScheduleTile extends StatelessWidget {
  const _ScheduleTile({
    required this.schedule,
    required this.onRun,
    required this.onRuns,
    required this.onMenu,
  });

  final AgentSchedule schedule;
  final VoidCallback onRun;
  final VoidCallback onRuns;
  final VoidCallback onMenu;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tone = !schedule.enabled
        ? StatusTone.neutral
        : schedule.lastError != null
        ? StatusTone.warning
        : StatusTone.success;
    return GlassCard(
      padding: const EdgeInsets.all(16),
      radius: 20,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  schedule.name,
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              StatusPill(
                label: schedule.enabled ? 'Active' : 'Paused',
                tone: tone,
              ),
              const SizedBox(width: 4),
              IconButton(
                tooltip: 'Schedule actions',
                onPressed: onMenu,
                icon: const Icon(Icons.more_vert),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '${schedule.agentId} · ${schedule.cadence} · ${schedule.timezone}',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            schedule.nextRunAt == null
                ? 'No next run scheduled'
                : 'Next run ${_relativeTime(schedule.nextRunAt)}',
            style: theme.textTheme.bodySmall,
          ),
          if (schedule.lastError != null) ...[
            const SizedBox(height: 6),
            Text(
              schedule.lastError!,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.error,
              ),
            ),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              FilledButton.tonalIcon(
                onPressed: onRun,
                icon: const Icon(Icons.play_arrow, size: 18),
                label: const Text('Run now'),
              ),
              const SizedBox(width: 8),
              TextButton.icon(
                onPressed: onRuns,
                icon: const Icon(Icons.history, size: 18),
                label: const Text('History'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class NotificationDetailPage extends StatefulWidget {
  const NotificationDetailPage({super.key, required this.notification});

  final AgentNotification notification;

  @override
  State<NotificationDetailPage> createState() => _NotificationDetailPageState();
}

class _NotificationDetailPageState extends State<NotificationDetailPage> {
  bool _running = false;

  ViraApi? get _api => AppScope.of(context, listen: false).api;

  Future<void> _runSchedule() async {
    final scheduleId = widget.notification.scheduleId;
    if (scheduleId == null) return;
    setState(() => _running = true);
    try {
      await _api?.runAgentSchedule(scheduleId);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Schedule queued for the next tick.')),
      );
    } on ViraApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  Future<void> _openRun() async {
    final scheduleId = widget.notification.scheduleId;
    final runId = widget.notification.runId;
    if (scheduleId == null || runId == null) return;
    try {
      final runs = await _api?.agentScheduleRuns(scheduleId, limit: 100);
      AgentScheduleRun? match;
      for (final item in runs ?? const <AgentScheduleRun>[]) {
        if (item.runId == runId) {
          match = item;
          break;
        }
      }
      if (!mounted) return;
      if (match == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Run details are not available yet.')),
        );
        return;
      }
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => AgentRunDetailPage(
            scheduleId: scheduleId,
            runId: match!.id,
            title: widget.notification.title,
          ),
        ),
      );
    } on ViraApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final notification = widget.notification;
    return Scaffold(
      appBar: AppBar(title: const Text('Agent update')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            notification.title,
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '${_relativeTime(notification.createdAt)} · ${notification.channel}',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: 16),
          GlassCard(
            padding: const EdgeInsets.all(18),
            child: SelectableText(
              notification.body.isEmpty
                  ? 'This update has no text body.'
                  : notification.body,
              style: theme.textTheme.bodyMedium?.copyWith(height: 1.55),
            ),
          ),
          if (notification.scheduleId != null) ...[
            const SizedBox(height: 16),
            Row(
              children: [
                FilledButton.icon(
                  onPressed: _running ? null : _runSchedule,
                  icon: _running
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.play_arrow),
                  label: const Text('Run schedule now'),
                ),
                if (notification.runId != null) ...[
                  const SizedBox(width: 8),
                  OutlinedButton.icon(
                    onPressed: _openRun,
                    icon: const Icon(Icons.timeline),
                    label: const Text('Open run'),
                  ),
                ],
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class AgentScheduleRunsPage extends StatefulWidget {
  const AgentScheduleRunsPage({super.key, required this.schedule});

  final AgentSchedule schedule;

  @override
  State<AgentScheduleRunsPage> createState() => _AgentScheduleRunsPageState();
}

class _AgentScheduleRunsPageState extends State<AgentScheduleRunsPage> {
  List<AgentScheduleRun> _runs = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = AppScope.of(context, listen: false).api;
    if (api == null) return;
    try {
      final runs = await api.agentScheduleRuns(widget.schedule.id);
      if (!mounted) return;
      setState(() {
        _runs = runs;
        _loading = false;
        _error = null;
      });
    } on ViraApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.schedule.name)),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 60),
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_error != null)
              EmptyState(
                icon: Icons.cloud_off_outlined,
                title: 'Cannot load runs',
                message: _error!,
              )
            else if (_runs.isEmpty)
              const EmptyState(
                icon: Icons.history,
                title: 'No runs yet',
                message: 'Run this schedule now or wait for its next trigger.',
              )
            else
              for (final run in _runs) ...[
                GlassCard(
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => AgentRunDetailPage(
                        scheduleId: widget.schedule.id,
                        runId: run.id,
                        title: widget.schedule.name,
                      ),
                    ),
                  ),
                  padding: const EdgeInsets.all(16),
                  radius: 20,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          StatusPill(
                            label: run.status,
                            tone: run.ok
                                ? StatusTone.success
                                : StatusTone.error,
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              _relativeTime(run.completedAt ?? run.startedAt),
                              textAlign: TextAlign.right,
                              style: Theme.of(context).textTheme.labelSmall,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        (run.error.isNotEmpty ? run.error : run.result).isEmpty
                            ? 'No result recorded.'
                            : (run.error.isNotEmpty ? run.error : run.result),
                        maxLines: 4,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 10),
              ],
          ],
        ),
      ),
    );
  }
}

class AgentRunDetailPage extends StatefulWidget {
  const AgentRunDetailPage({
    super.key,
    required this.scheduleId,
    required this.runId,
    required this.title,
  });

  final String scheduleId;
  final String runId;
  final String title;

  @override
  State<AgentRunDetailPage> createState() => _AgentRunDetailPageState();
}

class _AgentRunDetailPageState extends State<AgentRunDetailPage> {
  AgentScheduleRunDetail? _detail;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = AppScope.of(context, listen: false).api;
    if (api == null) return;
    try {
      final detail = await api.agentScheduleRun(
        widget.scheduleId,
        widget.runId,
      );
      if (!mounted) return;
      setState(() {
        _detail = detail;
        _loading = false;
        _error = null;
      });
    } on ViraApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final detail = _detail;
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (_loading)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 60),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_error != null)
            EmptyState(
              icon: Icons.cloud_off_outlined,
              title: 'Cannot load run',
              message: _error!,
            )
          else if (detail != null) ...[
            Row(
              children: [
                StatusPill(
                  label: detail.run.status,
                  tone: detail.run.ok ? StatusTone.success : StatusTone.error,
                ),
                const SizedBox(width: 8),
                Text(
                  _relativeTime(detail.run.completedAt ?? detail.run.startedAt),
                  style: theme.textTheme.bodySmall,
                ),
              ],
            ),
            const SizedBox(height: 16),
            GlassCard(
              padding: const EdgeInsets.all(18),
              child: SelectableText(
                detail.run.error.isNotEmpty
                    ? detail.run.error
                    : detail.run.result.isEmpty
                    ? 'No result recorded.'
                    : detail.run.result,
                style: theme.textTheme.bodyMedium?.copyWith(height: 1.55),
              ),
            ),
            if (detail.timeline.isNotEmpty) ...[
              const SizedBox(height: 20),
              Text(
                'Timeline',
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 8),
              for (final event in detail.timeline)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: GlassCard(
                    padding: const EdgeInsets.all(12),
                    radius: 14,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          event['type']?.toString() ?? 'event',
                          style: theme.textTheme.labelMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          event['data'].toString(),
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ],
        ],
      ),
    );
  }
}

String _relativeTime(DateTime? time) {
  if (time == null) return 'Unknown time';
  final now = DateTime.now();
  final delta = now.difference(time);
  if (delta.isNegative) {
    final until = time.difference(now);
    if (until.inMinutes < 60) return 'in ${until.inMinutes} min';
    if (until.inHours < 24) return 'in ${until.inHours} h';
    return 'in ${until.inDays} d';
  }
  if (delta.inMinutes < 1) return 'just now';
  if (delta.inMinutes < 60) return '${delta.inMinutes} min ago';
  if (delta.inHours < 24) return '${delta.inHours} h ago';
  if (delta.inDays < 7) return '${delta.inDays} d ago';
  return '${time.year}-${time.month.toString().padLeft(2, '0')}-'
      '${time.day.toString().padLeft(2, '0')}';
}
