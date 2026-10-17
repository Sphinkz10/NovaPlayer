package com.novacinema.connect.core

enum class PlaybackOutcome { DIRECT_PLAY, CONTAINER_REMUX, AUDIO_TRANSCODE, TRANSCODE_APPROVED, BLOCK_NO_ACCESS, BLOCK_NO_MEDIA, BLOCK_UNSUPPORTED_VIDEO, BLOCK_UNSUPPORTED_AUDIO, BLOCK_UNSUPPORTED_CONTAINER, BLOCK_UNSUPPORTED_SUBTITLE, BLOCK_INSUFFICIENT_BANDWIDTH }
data class PlaybackInputs(
    val accountAuthorized: Boolean,
    val mediaAvailable: Boolean,
    val videoCodecSupported: Boolean,
    val audioCodecSupported: Boolean,
    val audioTranscodeAllowed: Boolean,
    val bitrateMbps: Double,
    val measuredCapacityMbps: Double,
    val userOptedIntoVideoTranscode: Boolean,
    val adminAllowsVideoTranscode: Boolean,
    val containerSupported: Boolean = true,
    val containerRemuxAllowed: Boolean = false,
    val subtitleSupported: Boolean = true
)
object PlaybackPolicy {
    fun decide(i: PlaybackInputs): PlaybackOutcome {
        if (!i.accountAuthorized) return PlaybackOutcome.BLOCK_NO_ACCESS
        if (!i.mediaAvailable) return PlaybackOutcome.BLOCK_NO_MEDIA
        if (!i.videoCodecSupported) {
            return if (i.userOptedIntoVideoTranscode && i.adminAllowsVideoTranscode) PlaybackOutcome.TRANSCODE_APPROVED
            else PlaybackOutcome.BLOCK_UNSUPPORTED_VIDEO
        }
        if (!i.bitrateMbps.isFinite() || !i.measuredCapacityMbps.isFinite() || i.bitrateMbps <= 0 || i.measuredCapacityMbps <= 0 || i.bitrateMbps > i.measuredCapacityMbps * .8)
            return if (i.userOptedIntoVideoTranscode && i.adminAllowsVideoTranscode) PlaybackOutcome.TRANSCODE_APPROVED
            else PlaybackOutcome.BLOCK_INSUFFICIENT_BANDWIDTH
        if (!i.subtitleSupported) return PlaybackOutcome.BLOCK_UNSUPPORTED_SUBTITLE
        if (!i.containerSupported && !i.containerRemuxAllowed) return PlaybackOutcome.BLOCK_UNSUPPORTED_CONTAINER
        if (!i.audioCodecSupported) return if (i.audioTranscodeAllowed) PlaybackOutcome.AUDIO_TRANSCODE else PlaybackOutcome.BLOCK_UNSUPPORTED_AUDIO
        if (!i.containerSupported) return PlaybackOutcome.CONTAINER_REMUX
        return PlaybackOutcome.DIRECT_PLAY
    }
}

/** Rejects full-tunnel, broad LAN access and invalid CIDRs. Kept deliberately strict for POC. */
object RouteGuard {
    /** IPv4-only in the POC; production can add validated IPv6 ULA host routes. */
    fun isPrivateGatewayHost(host: String): Boolean {
        val fields = host.split('.')
        if (fields.size != 4 || fields.any { it.isEmpty() || it.length > 3 || !it.all(Char::isDigit) }) return false
        val oct = fields.map { it.toIntOrNull() ?: return false }
        if (oct.any { it !in 0..255 }) return false
        return oct[0] == 10 || (oct[0] == 172 && oct[1] in 16..31) ||
            (oct[0] == 192 && oct[1] == 168) || (oct[0] == 100 && oct[1] in 64..127)
    }

    fun allowedHostRoutes(allowedIps: String, gatewayHosts: Set<String>): Boolean {
        if (gatewayHosts.isEmpty() || gatewayHosts.any { !isPrivateGatewayHost(it) }) return false
        val entries = allowedIps.split(',').map(String::trim)
        if (entries.isEmpty() || entries.size > 8 || entries.size != entries.toSet().size) return false
        return entries.all { entry ->
            val fields = entry.split('/')
            fields.size == 2 && fields[1] == "32" && isPrivateGatewayHost(fields[0]) && fields[0] in gatewayHosts
        }
    }
}

data class SessionAuthorization(val viewerAllowed: Boolean, val jellyfinLibraryAllowed: Boolean, val hasSource: Boolean, val streamingPathPrivate: Boolean)
object AuthorizationPolicy {
    fun mayIssuePlaybackSession(s: SessionAuthorization): Boolean = s.viewerAllowed && s.jellyfinLibraryAllowed && s.hasSource && s.streamingPathPrivate
}
