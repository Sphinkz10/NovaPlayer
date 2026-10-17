plugins { id("org.jetbrains.kotlin.jvm") }
kotlin { jvmToolchain(17) }
dependencyLocking { lockAllConfigurations() }
tasks.register<JavaExec>("verifyCore") {
    dependsOn(tasks.testClasses)
    classpath = sourceSets["test"].runtimeClasspath
    mainClass.set("com.novacinema.connect.core.POCTest")
}
