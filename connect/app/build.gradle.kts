plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "com.novacinema.connect"
    compileSdk = 35
    defaultConfig { applicationId = "com.novacinema.connect.poc"; minSdk = 26; targetSdk = 35; versionCode = 3; versionName = "0.3" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildTypes { release { isMinifyEnabled = false } }
}
android.sourceSets["main"].java.srcDir("../core/src/main/kotlin")
dependencies {
    implementation("com.wireguard.android:tunnel:1.0.20260102")
}
