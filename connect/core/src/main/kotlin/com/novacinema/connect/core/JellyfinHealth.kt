package com.novacinema.connect.core

enum class JellyfinStatus {
    READY, SETUP_REQUIRED, AUTH_REQUIRED, FORBIDDEN, WRONG_ENDPOINT,
    RATE_LIMITED, TEMPORARILY_UNAVAILABLE, REDIRECT_REJECTED, TLS_VALIDATION_FAILED, SECURITY_BLOCKED, SERVER_IDENTITY_MISMATCH, UNEXPECTED_RESPONSE, OFFLINE
}
data class PublicServerInfo(val serverId: String?, val productName: String?, val startupWizardCompleted: Boolean?)
data class JellyfinProbeResult(val status: JellyfinStatus, val retryable: Boolean, val retryAfterSeconds: Int? = null)

/** Pure evaluator: no tokens, device information or server secrets in diagnostic text. */
object JellyfinHealth {
    fun evaluate(
        httpStatus: Int?,
        info: PublicServerInfo? = null,
        retryAfterSeconds: Int? = null,
        expectedServerId: String? = null
    ): JellyfinProbeResult {
        if (httpStatus == null) return JellyfinProbeResult(JellyfinStatus.OFFLINE, true)
        return when (httpStatus) {
            200 -> when {
                info == null || !info.productName.equals("Jellyfin", ignoreCase = true) || info.serverId.isNullOrBlank() ->
                    JellyfinProbeResult(JellyfinStatus.UNEXPECTED_RESPONSE, false)
                expectedServerId != null && (expectedServerId.isBlank() || info.serverId != expectedServerId) ->
                    JellyfinProbeResult(JellyfinStatus.SERVER_IDENTITY_MISMATCH, false)
                info.startupWizardCompleted == false -> JellyfinProbeResult(JellyfinStatus.SETUP_REQUIRED, false)
                info.startupWizardCompleted != true -> JellyfinProbeResult(JellyfinStatus.UNEXPECTED_RESPONSE, false)
                else -> JellyfinProbeResult(JellyfinStatus.READY, false)
            }
            401 -> JellyfinProbeResult(JellyfinStatus.AUTH_REQUIRED, false)
            403 -> JellyfinProbeResult(JellyfinStatus.FORBIDDEN, false)
            404 -> JellyfinProbeResult(JellyfinStatus.WRONG_ENDPOINT, false)
            408, 425, 500, 502, 503, 504 -> JellyfinProbeResult(JellyfinStatus.TEMPORARILY_UNAVAILABLE, true)
            429 -> JellyfinProbeResult(JellyfinStatus.RATE_LIMITED, true, retryAfterSeconds?.coerceIn(1, 3600))
            in 300..399 -> JellyfinProbeResult(JellyfinStatus.REDIRECT_REJECTED, false)
            else -> JellyfinProbeResult(JellyfinStatus.UNEXPECTED_RESPONSE, false)
        }
    }
}

enum class RetryAction { RETRY_WITH_DELAY, REQUIRE_USER_ACTION, NONE }
object RecoveryPolicy {
    fun action(outcome: JellyfinProbeResult): RetryAction = when {
        outcome.status == JellyfinStatus.READY -> RetryAction.NONE
        outcome.retryable -> RetryAction.RETRY_WITH_DELAY
        else -> RetryAction.REQUIRE_USER_ACTION
    }
    fun retryDelaySeconds(previousAttempts: Int, requestedRetryAfter: Int? = null): Int {
        val safe = (1 shl previousAttempts.coerceIn(0, 6)).coerceAtMost(60)
        return (requestedRetryAfter ?: safe).coerceIn(1, 3600)
    }
}
