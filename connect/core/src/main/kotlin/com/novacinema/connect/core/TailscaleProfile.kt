package com.novacinema.connect.core

import java.net.URI

/** Public setup authorization received through the associated server's pinned API.
 * Does not authorize tailnet membership or contain an enrollment secret.
 */
class TailscaleProfile(base:SavedDevice, val serverId:String, val deviceId:String, val accountId:String?,
    val baseOrigin:String, val controlOrigin:String, val clientOrigin:String, val revision:Int,
    val issuedAt:Long, val expiresAt:Long, now:Long=System.currentTimeMillis()/1000) {
    val trust:ServerTrust
    val gateway:String
    init {
        require(serverId==base.trust.serverId && deviceId==base.tokens.deviceId && accountId==base.accountId)
        require(baseOrigin==base.trust.origin && ServerTrust.validOrigin(baseOrigin))
        require(validControlOrigin(controlOrigin) && validGatewayOrigin(clientOrigin) && revision>=1)
        require(issuedAt in 1..(now+30) && expiresAt>now && expiresAt-issuedAt in 1..86400)
        gateway=URI(clientOrigin).host
        trust=ServerTrust.tailscale(clientOrigin,base.trust)
    }
    override fun toString()="TailscaleProfile(public authorization)"
    companion object {
        fun overlayV4(host:String):Boolean {
            val octets=host.split('.').map { it.toIntOrNull() ?: return false }
            return octets.size==4 && octets.all { it in 0..255 } && octets.joinToString(".")==host &&
                octets[0]==100 && octets[1] in 64..127
        }
        fun validGatewayOrigin(value:String):Boolean = runCatching {
            val uri=URI(value)
            uri.scheme=="https" && uri.port in 1024..65535 && overlayV4(uri.host ?: "") &&
                value=="https://${uri.host}:${uri.port}"
        }.getOrDefault(false)
        fun validControlOrigin(value:String):Boolean = runCatching {
            val uri=URI(value);val host=uri.host ?: return false
            // Canonical HTTPS origin. No DNS resolution while parsing a profile.
            val labels=host.split('.')
            uri.scheme=="https" && uri.rawUserInfo==null && uri.rawQuery==null && uri.rawFragment==null &&
                uri.rawPath.isNullOrEmpty() && (uri.port==-1 || uri.port in 1..65535) &&
                host.length<=253 && labels.all { it.matches(Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")) } &&
                value=="https://$host"+(if(uri.port==-1) "" else ":${uri.port}")
        }.getOrDefault(false)
    }
}
