<template>
  <el-container style="min-height:100vh">
    <el-header style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #eaeaea">
      <b>Harness Workspace</b>
      <el-menu mode="horizontal" :default-active="$route.path" router>
        <el-menu-item index="/">我的空间</el-menu-item>
        <el-menu-item index="/admin">管理</el-menu-item>
      </el-menu>
    </el-header>
    <el-main><router-view /></el-main>
  </el-container>
</template>
