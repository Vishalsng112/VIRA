import 'package:flutter/widgets.dart';

/// Shared responsive measurements.
///
/// Keep breakpoints and content caps here so mobile, tablet and web layouts do
/// not drift apart page by page.
abstract final class ViraLayout {
  /// Below this width the phone layout (bottom navigation) is used.
  static const double desktopBreakpoint = 760;

  /// Above this width the navigation rail can show labels.
  static const double extendedRailBreakpoint = 1180;

  /// Maximum readable width for the main content column on large screens.
  static const double contentMaxWidth = 1280;

  /// Phone-width content gets tighter type, padding and controls.
  static const double compactBreakpoint = 600;

  static bool isCompact(BuildContext context) =>
      MediaQuery.sizeOf(context).width < compactBreakpoint;

  static double pagePadding(BuildContext context) =>
      isCompact(context) ? 16 : 20;

  static double cardPadding(BuildContext context) =>
      isCompact(context) ? 16 : 20;

  static double gap(BuildContext context) => isCompact(context) ? 12 : 14;

  static EdgeInsets pageInsets(BuildContext context) {
    final padding = pagePadding(context);
    return EdgeInsets.fromLTRB(padding, padding, padding, padding + 8);
  }
}
