package com.novacinema.connect

import android.content.Context
import android.os.SystemClock
import com.novacinema.connect.core.*
import org.json.JSONObject
import java.io.IOException

/** JSON from the already pinned device API; no certificate or auth key accepted. */
internal fun tailscaleProfile(raw:JSONObject,base:SavedDevice):TailscaleProfile {
    require(raw.keys().asSequence().toSet()==setOf("schema_version","provider","server_id","device_id","account_id",
        "base_origin","control_origin","client_origin","revision","issued_at","expires_at"))
    require(raw.integer("schema_version")==1 && raw.string("provider")=="tailscale")
    fun seconds(key:String):Long {
        val value=raw.get(key);require(value is Int || value is Long);return (value as Number).toLong()
    }
    return TailscaleProfile(base,raw.string("server_id"),raw.string("device_id"),
        if(raw.isNull("account_id"))null else raw.string("account_id"),raw.string("base_origin"),
        raw.string("control_origin"),raw.string("client_origin"),raw.integer("revision"),seconds("issued_at"),seconds("expires_at"))
}

/** Shares the Cinema clients, identity checks and player with LAN/WireGuard.
 * The native adapter is supplied only by the explicit laboratory variant for now.
 */
internal object RemoteTailscaleRuntime {
    private class Route(val base:SavedDevice,val profile:TailscaleProfile,val deadline:Long,val live:()->Boolean)
    @Volatile private var route:Route?=null
    private fun prefs(context:Context)=context.getSharedPreferences("nova_tailscale_selection",Context.MODE_PRIVATE)
    fun selected(context:Context)=prefs(context).getBoolean("selected",false)
    fun activate(context:Context,base:SavedDevice,profile:TailscaleProfile,live:()->Boolean) {
        check(!RemoteWireGuardRuntime.selected(context) && live())
        require(profile.serverId==base.trust.serverId && profile.deviceId==base.tokens.deviceId && profile.accountId==base.accountId &&
            profile.baseOrigin==base.trust.origin && profile.trust.certificateDer.contentEquals(base.trust.certificateDer) &&
            profile.expiresAt>System.currentTimeMillis()/1000)
        check(sameBase(base,DeviceSessionStore(context).loadBase() ?: error("Association required")))
        check(prefs(context).edit().putBoolean("selected",true).commit())
        route=Route(base,profile,SystemClock.elapsedRealtime()+profile.expiresAt*1000-System.currentTimeMillis(),live)
    }
    fun project(context:Context,saved:SavedDevice):SavedDevice {
        if(!selected(context))return saved
        val active=route ?: throw IOException("Reconnect the selected Tailscale transport")
        if(!sameBase(saved,active.base) || SystemClock.elapsedRealtime()>=active.deadline ||
            System.currentTimeMillis()/1000>=active.profile.expiresAt || !active.live())
            throw IOException("Tailscale transport unavailable")
        return SavedDevice(active.profile.trust,saved.tokens,saved.refreshDeadline,saved.refreshPending,saved.accountId)
    }
    private fun sameBase(a:SavedDevice,b:SavedDevice)=a.trust.origin==b.trust.origin && a.trust.serverId==b.trust.serverId &&
        a.trust.certificateDer.contentEquals(b.trust.certificateDer) && a.tokens.deviceId==b.tokens.deviceId && a.accountId==b.accountId
    fun persistent(saved:SavedDevice):SavedDevice {
        val active=route ?: return saved
        if(saved.trust.origin!=active.profile.trust.origin)return saved
        require(saved.trust.serverId==active.base.trust.serverId && saved.tokens.deviceId==active.base.tokens.deviceId &&
            saved.accountId==active.base.accountId && saved.trust.certificateDer.contentEquals(active.base.trust.certificateDer))
        return SavedDevice(active.base.trust,saved.tokens,saved.refreshDeadline,saved.refreshPending,saved.accountId)
    }
    fun forget(context:Context) { check(prefs(context).edit().clear().commit());route=null }
    // Closing the native tunnel precedes returning explicitly to LAN. Losing the
    // service leaves selection set, so process death cannot silently choose LAN.
    fun useLanAfterDisconnect(context:Context) { forget(context) }
}
