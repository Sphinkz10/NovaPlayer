package com.novacinema.connect.core

import java.net.URI

enum class LinkMode { LAN, PRIVATE_VPN, UNAVAILABLE }
enum class LinkReason { LAN_VERIFIED, VPN_VERIFIED, NEEDS_ADMIN_PROVISIONING, NEEDS_ANDROID_CONSENT, NEEDS_VPN_CONNECTION, NO_PRIVATE_ROUTE }
data class ConnectionInputs(
    val lanVerified: Boolean,
    val hasAdminProvisionedProfile: Boolean,
    val vpnConsentGranted: Boolean,
    val vpnTunnelUp: Boolean,
    val lanBaseUrl: String?,
    val vpnBaseUrl: String?
)
data class ConnectionDecision(val mode: LinkMode, val reason: LinkReason, val baseUrl: String? = null)

/** Fail-closed: never attempt public Jellyfin as an undocumented fallback. */
object ConnectionPolicy {
    fun decide(i: ConnectionInputs): ConnectionDecision {
        val lan = i.lanBaseUrl?.takeIf { EndpointValidator.isValidPrivateLan(it) }
        if (i.lanVerified && lan != null) return ConnectionDecision(LinkMode.LAN, LinkReason.LAN_VERIFIED, lan)
        if (!i.hasAdminProvisionedProfile || i.vpnBaseUrl == null || !EndpointValidator.isValid(i.vpnBaseUrl, true))
            return ConnectionDecision(LinkMode.UNAVAILABLE, LinkReason.NEEDS_ADMIN_PROVISIONING)
        if (!i.vpnConsentGranted) return ConnectionDecision(LinkMode.UNAVAILABLE, LinkReason.NEEDS_ANDROID_CONSENT)
        if (!i.vpnTunnelUp) return ConnectionDecision(LinkMode.UNAVAILABLE, LinkReason.NEEDS_VPN_CONNECTION)
        return ConnectionDecision(LinkMode.PRIVATE_VPN, LinkReason.VPN_VERIFIED, i.vpnBaseUrl)
    }
}

object EndpointValidator {
    /** Production uses HTTPS on LAN and VPN; only private numeric LAN endpoints are trusted by ConnectionPolicy. */
    fun isValidPrivateLan(value: String): Boolean =
        isValid(value, vpn = false) && RouteGuard.isPrivateGatewayHost(runCatching { URI(value).host }.getOrNull() ?: "")

    /** Loopback HTTP exists solely for JVM mock tests. */
    fun isValid(value: String, vpn: Boolean, allowLoopbackHttpForTests: Boolean = false): Boolean {
        val uri = runCatching { URI(value) }.getOrNull() ?: return false
        val scheme = uri.scheme?.lowercase() ?: return false
        if (scheme != "https") {
            if (vpn || !allowLoopbackHttpForTests || scheme != "http" || uri.host !in setOf("127.0.0.1", "localhost", "[::1]")) return false
        }
        if (uri.host.isNullOrBlank() || uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null) return false
        // Avoid URL parser/path disagreements and ambiguous proxy prefixes.
        if (value != value.trim() || value.any { it.isISOControl() || it == '\\' }) return false
        if (Regex("(?i)%2e|%2f|%5c|%00").containsMatchIn(uri.rawPath ?: "")) return false
        if (vpn && !RouteGuard.isPrivateGatewayHost(uri.host)) return false
        if (uri.port > 65535 || uri.port == 0 || uri.port < -1) return false
        if (uri.path?.contains("..") == true || uri.rawPath?.contains("%2f", true) == true) return false
        return true
    }

    fun publicInfoUrl(baseUrl: String, allowLoopbackHttpForTests: Boolean = false): URI {
        require(isValid(baseUrl, vpn = false, allowLoopbackHttpForTests = allowLoopbackHttpForTests)) { "Invalid Jellyfin endpoint" }
        val u = URI(baseUrl.trimEnd('/') + "/")
        return u.resolve("System/Info/Public")
    }
}
