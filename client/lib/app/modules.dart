import 'package:material_ui/material_ui.dart';

import '../features/activity/activity_page.dart';
import '../features/admin/admin_page.dart';
import '../features/chat/chat_page.dart';
import '../features/dashboard/dashboard_page.dart';
import '../features/devices/devices_page.dart';
import '../features/insights/insights_page.dart';
import '../features/settings/settings_page.dart';

class AppModule {
  const AppModule({
    required this.id,
    required this.label,
    required this.icon,
    required this.selectedIcon,
    required this.builder,
  });

  final String id;
  final String label;
  final IconData icon;
  final IconData selectedIcon;
  final WidgetBuilder builder;
}

/// The navigation shell is generated from these modules. Add a module here to
/// add a feature; remove it here and its page is no longer reachable.
const _dashboardModule = AppModule(
  id: 'dashboard',
  label: 'Overview',
  icon: Icons.space_dashboard_outlined,
  selectedIcon: Icons.space_dashboard,
  builder: _dashboard,
);
const _insightsModule = AppModule(
  id: 'insights',
  label: 'Insights',
  icon: Icons.insights_outlined,
  selectedIcon: Icons.insights,
  builder: _insights,
);
const _chatModule = AppModule(
  id: 'chat',
  label: 'Chat',
  icon: Icons.auto_awesome_outlined,
  selectedIcon: Icons.auto_awesome,
  builder: _chat,
);
const _activityModule = AppModule(
  id: 'activity',
  label: 'Activity',
  icon: Icons.bolt_outlined,
  selectedIcon: Icons.bolt,
  builder: _activity,
);
const _devicesModule = AppModule(
  id: 'devices',
  label: 'Devices',
  icon: Icons.devices_other_outlined,
  selectedIcon: Icons.devices_other,
  builder: _devices,
);
const _adminModule = AppModule(
  id: 'admin',
  label: 'Admin',
  icon: Icons.admin_panel_settings_outlined,
  selectedIcon: Icons.admin_panel_settings,
  builder: _admin,
);
const _settingsModule = AppModule(
  id: 'settings',
  label: 'Settings',
  icon: Icons.settings_outlined,
  selectedIcon: Icons.settings,
  builder: _settings,
);

List<AppModule> appModulesFor({required bool isAdmin}) => [
  _dashboardModule,
  _chatModule,
  _insightsModule,
  _activityModule,
  _devicesModule,
  if (isAdmin) _adminModule,
  _settingsModule,
];

Widget _dashboard(BuildContext context) => const DashboardPage();
Widget _chat(BuildContext context) => const ChatPage();
Widget _insights(BuildContext context) => const InsightsPage();
Widget _activity(BuildContext context) => const ActivityPage();
Widget _devices(BuildContext context) => const DevicesPage();
Widget _admin(BuildContext context) => const AdminPage();
Widget _settings(BuildContext context) => const SettingsPage();
