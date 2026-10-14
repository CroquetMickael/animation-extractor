-- /animx <dict> <clip> [speed=1.0] [flag=0] [blend=4.0] [noik]   play a clip on your ped, nothing else around it
-- /animx stop                                                    clear the task
-- "noik" switches off the game's leg/arm/head/torso IK while the clip plays (they correct the limbs every
-- frame: feet pulled onto the ground, hands placed), to tell an animation problem from an IK one.
-- The .ycd goes in this resource's stream/ folder (or any resource's stream/ folder).

local function loadDict(dict)
    RequestAnimDict(dict)
    local deadline = GetGameTimer() + 5000
    while not HasAnimDictLoaded(dict) do
        if GetGameTimer() > deadline then return false end
        Wait(0)
    end
    return true
end

local function setIk(ped, enabled)
    SetPedCanLegIk(ped, enabled)
    SetPedLegIkMode(ped, enabled and 2 or 0)
    SetPedCanArmIk(ped, enabled)
    SetPedCanHeadIk(ped, enabled)
    SetPedCanTorsoIk(ped, enabled)
end

RegisterCommand('animx', function(_, args)
    local ped = PlayerPedId()
    if args[1] == 'stop' or not args[1] then
        ClearPedTasks(ped)
        setIk(ped, true)
        return
    end

    local dict, clip = args[1], args[2]
    local speed = tonumber(args[3] or '1.0') or 1.0
    local flag = tonumber(args[4] or '0') or 0
    local blend = tonumber(args[5] or '4.0') or 4.0
    local noIk = args[6] == 'noik'
    if not clip then
        print('^3/animx <dict> <clip> [speed] [flag] [blend] [noik]^7')
        return
    end
    if not loadDict(dict) then
        print(('^1animx: dictionnaire %s introuvable (le .ycd est-il dans un dossier stream/ ?)^7'):format(dict))
        return
    end

    local start = GetEntityCoords(ped)
    ClearPedTasksImmediately(ped)
    if noIk then setIk(ped, false) end
    TaskPlayAnim(ped, dict, clip, blend, -blend, -1, flag, 0.0, false, false, false)

    CreateThread(function()
        Wait(0)
        SetEntityAnimSpeed(ped, dict, clip, speed)
        local duration = GetAnimDuration(dict, clip)
        print(('^2animx: %s/%s %.2fs x%.2f flag %d blend %.1f IK %s^7'):format(dict, clip, duration, speed, flag, blend, noIk and 'OFF' or 'on'))
        local ends = GetGameTimer() + math.floor(duration / speed * 1000) + 100
        while GetGameTimer() < ends do
            if noIk then setIk(ped, false) end
            Wait(0)
        end
        if noIk and not (flag & 1 == 1) then setIk(ped, true) end
        print(('^2animx: déplacement %.2f m^7'):format(#(GetEntityCoords(ped) - start)))
    end)
end, false)
