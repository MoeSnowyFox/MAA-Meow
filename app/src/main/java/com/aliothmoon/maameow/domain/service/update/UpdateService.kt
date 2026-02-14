package com.aliothmoon.maameow.domain.service.update

import com.aliothmoon.maameow.data.model.update.UpdateProcessState
import com.aliothmoon.maameow.data.model.update.UpdateSource
import kotlinx.coroutines.flow.StateFlow
import java.io.File

/**
 * 更新服务统一门面
 * 提供资源更新和 App 更新的统一入口
 * 保持 API 兼容，内部委托给具体 Handler
 */
class UpdateService(
    private val resourceHandler: ResourceUpdateHandler,
    private val appHandler: AppUpdateHandler,
) {
    // ==================== 资源更新 ====================

    val resourceUpdateState: StateFlow<UpdateProcessState>
        get() = resourceHandler.state

    suspend fun checkResourceUpdate(current: String) {
        resourceHandler.checkUpdate(current)
    }

    suspend fun confirmAndDownloadResource(
        source: UpdateSource,
        cdk: String,
        currentVersion: String,
        dir: File
    ): Result<Unit> {
        return resourceHandler.confirmAndDownload(source, cdk, currentVersion, dir)
    }

    fun reset() {
        resourceHandler.resetState()
    }

    // ==================== App 更新 ====================

    val appUpdateState: StateFlow<UpdateProcessState>
        get() = appHandler.state

    suspend fun checkAppUpdate() {
        appHandler.checkUpdate()
    }

    suspend fun confirmAndDownloadApp(source: UpdateSource, cdk: String): Result<Unit> {
        return appHandler.confirmAndDownload(source, cdk)
    }

    fun resetAppUpdate() {
        appHandler.resetState()
    }
}
