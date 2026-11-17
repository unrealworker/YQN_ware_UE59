// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;
using System.Collections.Generic;

public class TestEditorTarget : TargetRules
{
	public TestEditorTarget( TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V8;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_9;
		if (Target.Platform == UnrealTargetPlatform.Win64)
		{
			// Installed family 14.44.35207 contains the UE 5.8 recommended 14.44.35229 toolchain.
			WindowsPlatform.CompilerVersion ??= "14.44.35207";
		}
		ExtraModuleNames.Add("Test");
	}
}
