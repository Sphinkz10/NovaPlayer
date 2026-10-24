package com.novacinema.connect.core

/** Stable wire IDs shared with the Server draft API. No brand/model allowlist. */
enum class ProviderId(val wireId: String) {
    WIREGUARD("wireguard"), TAILSCALE("tailscale"), NETBIRD("netbird");
    companion object { fun parse(value: String): ProviderId? = entries.find { it.wireId == value } }
}

data class DeviceCapabilities(val sdk: Int, val abis: Set<String>, val television: Boolean)
data class NativeEngineCapability(val provider: ProviderId, val compiled: Boolean, val abis: Set<String>)
enum class ProviderState {
    UNSUPPORTED_DEVICE, NOT_IMPLEMENTED, NEEDS_PROVISIONING, NEEDS_ANDROID_CONSENT,
    NEEDS_CONNECTION, VERIFYING_SERVICE, CONNECTED, REVOKED
}

data class ProviderObservation(
    val provisioned: Boolean = false,
    val consentGranted: Boolean = false,
    val tunnelUp: Boolean = false,
    val privateHttpsReachable: Boolean = false,
    val serverIdentityMatches: Boolean = false,
    val deviceAuthorized: Boolean = false,
    val revoked: Boolean = false
)

object ProviderRegistry {
    // ABIs observed in the pinned WireGuard AAR; no claims about other engines.
    val capabilities = listOf(
        NativeEngineCapability(ProviderId.WIREGUARD, true, setOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")),
        NativeEngineCapability(ProviderId.TAILSCALE, false, emptySet()),
        NativeEngineCapability(ProviderId.NETBIRD, false, emptySet())
    )

    fun evaluate(provider: ProviderId, device: DeviceCapabilities, observation: ProviderObservation): ProviderState {
        if (observation.revoked) return ProviderState.REVOKED
        if (device.sdk < 26) return ProviderState.UNSUPPORTED_DEVICE
        val engine = capabilities.single { it.provider == provider }
        if (!engine.compiled) return ProviderState.NOT_IMPLEMENTED
        if (device.abis.none { it in engine.abis }) return ProviderState.UNSUPPORTED_DEVICE
        if (!observation.provisioned) return ProviderState.NEEDS_PROVISIONING
        if (!observation.consentGranted) return ProviderState.NEEDS_ANDROID_CONSENT
        if (!observation.tunnelUp) return ProviderState.NEEDS_CONNECTION
        if (!observation.privateHttpsReachable || !observation.serverIdentityMatches || !observation.deviceAuthorized)
            return ProviderState.VERIFYING_SERVICE
        return ProviderState.CONNECTED
    }
}

/** Runtime contract: operations refer to a specific provider, never auto-fallback.
 * Credentials belong to the platform's encrypted provisioning store, not this model.
 * Implementations must serialize connect/disconnect and invalidate stale callbacks.
 */
interface NativeProviderEngine {
    val provider: ProviderId
    fun disconnect()
    fun isTunnelUp(): Boolean
}
