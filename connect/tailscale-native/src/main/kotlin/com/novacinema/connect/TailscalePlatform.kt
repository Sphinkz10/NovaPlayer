package com.novacinema.connect

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.ParcelFileDescriptor
import com.novacinema.engines.libtailscale.AppContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.NetworkInterface
import java.util.Collections

/** Platform callbacks for the pinned upstream API. No credential or remote diagnostic logging. */
internal class TailscalePlatform(private val context: Context, private val state: TailscaleStateStore,
                                 private val fixtureCA: ByteArray) : AppContext {
    override fun log(tag: String, logLine: String) { /* Upstream messages can contain auth URLs. */ }
    override fun encryptToPref(key: String, value: String) = state.write(key, value)
    override fun decryptFromPref(key: String): String = state.read(key)
    override fun getStateStoreKeysJSON(): String = JSONArray(state.keys().filter { it.startsWith("statestore-") }
        .map { it.removePrefix("statestore-") }).toString()
    override fun getOSVersion(): String = Build.VERSION.RELEASE
    override fun getSDKInt(): Long = Build.VERSION.SDK_INT.toLong()
    override fun getDeviceName() = "nova-cinema"
    override fun getInstallSource() = "NOVA"
    override fun shouldUseGoogleDNSFallback() = false
    override fun isChromeOS() = false
    override fun isClientLoggingEnabled() = false
    override fun getPlatformDNSConfig(): String {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val properties = manager.getLinkProperties(underlay()) ?: return ""
        return properties.dnsServers.mapNotNull { it.hostAddress }.joinToString(" ")
    }
    override fun getInterfacesAsJson(): String = JSONArray().apply {
        for (network in Collections.list(NetworkInterface.getNetworkInterfaces())) {
            runCatching {
                put(JSONObject().put("name", network.name).put("index", network.index).put("mtu", network.mtu)
                    .put("up", network.isUp).put("broadcast", network.interfaceAddresses.any { it.broadcast != null })
                    .put("loopback", network.isLoopback).put("pointToPoint", network.isPointToPoint)
                    .put("multicast", network.supportsMulticast()).put("addrs", JSONArray().apply {
                        network.interfaceAddresses.forEach { address ->
                            put(JSONObject().put("ip", address.address.hostAddress)
                                .put("prefixLen", address.networkPrefixLength.toInt()))
                        }
                    }))
            }
        }
    }.toString()
    private fun underlay(): android.net.Network? {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        return manager.allNetworks.firstOrNull { network ->
            manager.getNetworkCapabilities(network)?.let {
                it.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                    it.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            } == true
        }
    }
    override fun bindSocketToNetwork(fd: Int): Boolean = runCatching {
        val network = underlay() ?: return false
        ParcelFileDescriptor.fromFd(fd).use { network.bindSocket(it.fileDescriptor) }; true
    }.getOrDefault(false)
    // Only the disposable debug fixture supplies a CA. Normal release does not include this adapter yet.
    override fun getUserCACertsPEM(): ByteArray = fixtureCA.copyOf()
    private fun unset(): Nothing = throw java.io.IOException("policy not configured")
    override fun getSyspolicyStringValue(key: String): String = unset()
    override fun getSyspolicyBooleanValue(key: String): Boolean = unset()
    override fun getSyspolicyStringArrayJSONValue(key: String): String = unset()
    override fun hardwareAttestationKeySupported() = false
    override fun hardwareAttestationKeyCreate(): String = unset()
    override fun hardwareAttestationKeyRelease(id: String) { unset() }
    override fun hardwareAttestationKeyPublic(id: String): ByteArray = unset()
    override fun hardwareAttestationKeySign(id: String, data: ByteArray): ByteArray = unset()
    override fun hardwareAttestationKeyLoad(id: String) { unset() }
}
