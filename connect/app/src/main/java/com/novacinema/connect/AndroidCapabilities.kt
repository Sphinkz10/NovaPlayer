package com.novacinema.connect

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import com.novacinema.connect.core.DeviceCapabilities

object AndroidCapabilities {
    fun read(context: Context) = DeviceCapabilities(
        sdk = Build.VERSION.SDK_INT,
        abis = Build.SUPPORTED_ABIS.toSet(),
        television = context.packageManager.hasSystemFeature(PackageManager.FEATURE_LEANBACK)
    )
}
