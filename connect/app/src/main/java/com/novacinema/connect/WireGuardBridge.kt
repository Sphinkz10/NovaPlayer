package com.novacinema.connect

import android.content.Context
import android.net.VpnService
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import java.io.ByteArrayInputStream
import java.nio.charset.StandardCharsets
import com.novacinema.connect.core.RouteGuard
import com.novacinema.connect.core.EndpointValidator
import java.net.URI

/** A real tunnel adapter; tunnel negotiation cannot be tested without an Android device + endpoint. */
class WireGuardBridge(context: Context) {
    private val installedPackageName = context.packageName
    private val backend by lazy { GoBackend(context.applicationContext) }
    private val tunnel = object : Tunnel {
        override fun getName(): String = "nova-private"
        override fun onStateChange(newState: Tunnel.State) { /* UI state is checked via backend */ }
    }
    fun needsSystemConsent(context: Context): Boolean = VpnService.prepare(context) != null

    fun connect(configText: String, jellyfinUrl: String): Boolean {
        require(EndpointValidator.isValid(jellyfinUrl, vpn = true)) { "Invalid private endpoint" }
        val profile = Config.parse(ByteArrayInputStream(configText.toByteArray(StandardCharsets.UTF_8)))
        require(profile.`interface`.includedApplications == setOf(installedPackageName)) { "VPN must be limited to NOVA application" }
        require(profile.`interface`.excludedApplications.isEmpty()) { "Cannot use excluded-app fallback" }
        require(profile.peers.size == 1) { "Expected exactly one approved gateway peer" }
        val allAllowed = profile.peers.single().allowedIps.joinToString(",") { it.toString() }
        val urlHost = URI(jellyfinUrl).host ?: error("Jellyfin must be reached by a private numeric gateway address")
        require(RouteGuard.allowedHostRoutes(allAllowed, setOf(urlHost))) { "Only exact approved gateway host route allowed" }
        return backend.setState(tunnel, Tunnel.State.UP, profile) == Tunnel.State.UP
    }

    fun disconnect() { backend.setState(tunnel, Tunnel.State.DOWN, null) }
    fun isConnected(): Boolean = backend.getState(tunnel) == Tunnel.State.UP
}
