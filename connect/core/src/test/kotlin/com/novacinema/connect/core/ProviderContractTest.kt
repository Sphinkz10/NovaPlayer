package com.novacinema.connect.core

object ProviderContractTest {
    fun run(): Int {
        var count = 0
        fun expect(state: ProviderState, provider: ProviderId, device: DeviceCapabilities, observation: ProviderObservation = ProviderObservation()) {
            check(ProviderRegistry.evaluate(provider, device, observation) == state)
            count++
        }
        val tv = DeviceCapabilities(30, setOf("arm64-v8a"), true)
        val ready = ProviderObservation(true, true, true, true, true, true)
        // Architecture and OS decide compatibility, not a manufacturer string.
        for (abi in listOf("armeabi-v7a", "arm64-v8a", "x86", "x86_64")) {
            for (api in listOf(26, 30, 35)) {
                expect(ProviderState.NEEDS_PROVISIONING, ProviderId.WIREGUARD, tv.copy(sdk=api, abis=setOf(abi)))
            }
        }
        expect(ProviderState.UNSUPPORTED_DEVICE, ProviderId.WIREGUARD, tv.copy(sdk=25))
        expect(ProviderState.UNSUPPORTED_DEVICE, ProviderId.WIREGUARD, tv.copy(abis=setOf("unsupported")))
        expect(ProviderState.NEEDS_PROVISIONING, ProviderId.WIREGUARD, tv.copy(television=false))
        expect(ProviderState.NEEDS_ANDROID_CONSENT, ProviderId.WIREGUARD, tv, ready.copy(consentGranted=false))
        expect(ProviderState.NEEDS_CONNECTION, ProviderId.WIREGUARD, tv, ready.copy(tunnelUp=false))
        expect(ProviderState.VERIFYING_SERVICE, ProviderId.WIREGUARD, tv, ready.copy(privateHttpsReachable=false))
        expect(ProviderState.VERIFYING_SERVICE, ProviderId.WIREGUARD, tv, ready.copy(serverIdentityMatches=false))
        expect(ProviderState.VERIFYING_SERVICE, ProviderId.WIREGUARD, tv, ready.copy(deviceAuthorized=false))
        expect(ProviderState.CONNECTED, ProviderId.WIREGUARD, tv, ready)
        for (provider in ProviderId.entries) {
            expect(ProviderState.REVOKED, provider, tv, ready.copy(revoked=true))
            check(ProviderId.parse(provider.wireId) == provider); count++
        }
        // A working WireGuard engine must never be substituted for another provider.
        for (provider in listOf(ProviderId.TAILSCALE, ProviderId.NETBIRD)) {
            expect(ProviderState.NOT_IMPLEMENTED, provider, tv, ready)
        }
        check(ProviderId.parse("unknown") == null); count++
        return count
    }
}
