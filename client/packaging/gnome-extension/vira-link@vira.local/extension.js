import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import Gio from 'gi://Gio';

const IFACE_XML = `
<node>
  <interface name="org.vira.Link.WindowInfo">
    <method name="GetActiveWindow">
      <arg type="s" direction="out" name="window"/>
    </method>
  </interface>
</node>`;

export default class ViraLinkWindowInfoExtension extends Extension {
  enable() {
    this._exported = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
    this._exported.export(Gio.DBus.session, '/org/vira/Link/WindowInfo');
    this._nameId = Gio.DBus.session.own_name(
      'org.vira.Link.WindowInfo',
      Gio.BusNameOwnerFlags.NONE,
      null,
      null,
    );
  }

  disable() {
    if (this._nameId) {
      Gio.DBus.session.unown_name(this._nameId);
      this._nameId = 0;
    }
    if (this._exported) {
      this._exported.unexport();
      this._exported = null;
    }
  }

  GetActiveWindow() {
    const win = global.display.get_focus_window();
    if (!win) return '';
    return JSON.stringify({
      app_id:
        win.get_wm_class() ||
        win.get_gtk_application_id() ||
        win.get_sandboxed_app_id() ||
        win.get_wm_class_instance() ||
        '',
      title: win.get_name() || '',
      pid: win.get_pid() || 0,
    });
  }
}
