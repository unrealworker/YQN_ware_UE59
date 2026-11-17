// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;
using System.IO;
using System.Collections.Generic;

public class Test : ModuleRules
{
	public Test(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		// Existing telemetry translation units contain same-named internal helpers.
		bUseUnity = false;
	
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput", "UniversalCameraPlugin", "UMG" });

		PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore", "Json", "ApplicationCore", "GHSDisplayBootstrap", "RenderCore", "RHI", "AnimationCore" });
		// Native browser builds render locally and do not load desktop streaming encoders.
		if (Target.Platform != UnrealTargetPlatform.Wasm)
		{
			PrivateDependencyModuleNames.AddRange(new string[] { "WebBrowser", "PixelStreaming2", "PixelStreaming2Core", "PixelStreaming2Input", "AVCodecsCore", "NVENC" });
		}
		if (Target.Platform == UnrealTargetPlatform.Wasm)
		{
			// These loose files become explicit URL/SHA1 entries in the platform's wasm-manifest.json.
			// Stage only browser runtime assets, not the web test harness or authoring reports.
			string TwinRoot = Path.GetFullPath(Path.Combine(ModuleDirectory, "../../Content/GHSTwinUI"));
			var WebExtensions = new HashSet<string>(System.StringComparer.OrdinalIgnoreCase) { ".html", ".js", ".css", ".txt" };
			var AssetExtensions = new HashSet<string>(System.StringComparer.OrdinalIgnoreCase) { ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".ttf", ".woff", ".woff2", ".txt" };
			foreach (string File in Directory.GetFiles(Path.Combine(TwinRoot, "web"), "*", SearchOption.TopDirectoryOnly))
				if (WebExtensions.Contains(Path.GetExtension(File))) RuntimeDependencies.Add(File, StagedFileType.NonUFS);
			foreach (string File in Directory.GetFiles(Path.Combine(TwinRoot, "web/assets"), "*", SearchOption.AllDirectories))
				if (AssetExtensions.Contains(Path.GetExtension(File))) RuntimeDependencies.Add(File, StagedFileType.NonUFS);
			foreach (string File in Directory.GetFiles(Path.Combine(TwinRoot, "data"), "*", SearchOption.AllDirectories))
				if (Path.GetExtension(File).Equals(".json", System.StringComparison.OrdinalIgnoreCase) || Path.GetExtension(File).Equals(".csv", System.StringComparison.OrdinalIgnoreCase))
					RuntimeDependencies.Add(File, StagedFileType.NonUFS);
		}
		else
		{
			RuntimeDependencies.Add("$(ProjectDir)/Content/GHSTwinUI/web/...", StagedFileType.NonUFS);
			RuntimeDependencies.Add("$(ProjectDir)/Content/GHSTwinUI/data/...", StagedFileType.NonUFS);
		}
		RuntimeDependencies.Add("$(ProjectDir)/Content/GHSNormalWarehouse/HUD/Fonts/DroidSansFallback.ttf", StagedFileType.NonUFS);
		RuntimeDependencies.Add("$(ProjectDir)/Content/GHSNormalWarehouse/HUD/Fonts/LICENSE.txt", StagedFileType.NonUFS);

		// Uncomment if you are using Slate UI
		// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });
		
		// Uncomment if you are using online features
		// PrivateDependencyModuleNames.Add("OnlineSubsystem");

		// To include OnlineSubsystemSteam, add it to the plugins section in your uproject file with the Enabled attribute set to true
	}
}
