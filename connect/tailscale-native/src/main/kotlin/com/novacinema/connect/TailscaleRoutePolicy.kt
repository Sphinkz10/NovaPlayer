package com.novacinema.connect

import java.net.InetAddress
import java.net.URI

/** Provider-specific CGNAT validation; does not change LAN or WireGuard trust rules. */
internal class TailscaleRoutePolicy(val gateway: String) {
    init { require(isOverlayV4(gateway)) }
    var gatewayCovered = false
        private set
    var gatewayExcluded = false
        private set
    fun route(ip: String, prefix: Int) {
        if (':' in ip) {
            require(prefix in 48..128 && isOverlayV6(ip)); return
        }
        require(prefix in 10..32 && isOverlayV4(ip))
        if (contains(ip, prefix, gateway)) gatewayCovered = true
    }
    fun exclude(ip: String, prefix: Int) {
        if (':' !in ip && prefix in 0..32 && contains(ip, prefix, gateway)) gatewayExcluded = true
    }
    fun ready() { check(gatewayCovered && !gatewayExcluded) { "Approved gateway route absent" } }
    companion object {
        private fun octets(ip: String): List<Int>? = ip.split('.').map { it.toIntOrNull() ?: return null }
            .takeIf { it.size == 4 && it.all { part -> part in 0..255 } && it.joinToString(".") == ip }
        fun isOverlayV4(ip: String): Boolean = octets(ip)?.let { it[0] == 100 && it[1] in 64..127 } == true
        fun isOverlayV6(ip: String): Boolean = runCatching {
            require(ip.matches(Regex("[a-fA-F0-9:]+")))
            val bytes = InetAddress.getByName(ip).address
            bytes.size == 16 && bytes.take(6) == byteArrayOf(0xfd.toByte(), 0x7a, 0x11, 0x5c, 0xa1.toByte(), 0xe0.toByte()).toList()
        }.getOrDefault(false)
        private fun contains(network: String, prefix: Int, host: String): Boolean {
            val a = octets(network) ?: return false; val b = octets(host) ?: return false
            fun packed(parts: List<Int>) = parts.fold(0L) { n, v -> (n shl 8) or v.toLong() }
            val mask = if (prefix == 0) 0L else (0xffffffffL shl (32 - prefix)) and 0xffffffffL
            return (packed(a) and mask) == (packed(b) and mask)
        }
        fun controlOrigin(value: String): String {
            val uri = URI(value)
            require(uri.scheme == "https" && !uri.host.isNullOrEmpty() && uri.rawUserInfo == null &&
                uri.rawQuery == null && uri.rawFragment == null && uri.rawPath.isNullOrEmpty() &&
                (uri.port == -1 || uri.port in 1..65535) && value.length <= 2048)
            return value
        }
    }
}
