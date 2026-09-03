param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath
)

$ErrorActionPreference = 'Stop'
$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$settings = [System.Xml.XmlReaderSettings]::new()
$settings.DtdProcessing = [System.Xml.DtdProcessing]::Parse
$settings.XmlResolver = $null
$settings.MaxCharactersFromEntities = 1000000
$reader = [System.Xml.XmlReader]::Create($resolvedInput, $settings)

$travel = @{}
$classRooms = @{}
$exactOrdered = @{}
$safeRelations = @{}
$inRooms = $false
$rootRoomId = $null
$rootRoomDepth = -1
$inCourses = $false
$classId = $null
$classDepth = -1
$classRoomRequired = $true
$classRoomList = $null
$inDistributions = $false
$distributionType = $null
$distributionRequired = $false
$distributionDepth = -1
$distributionClasses = $null
$rawPairOccurrences = [int64]0
$safeEvaluations = [int64]0
$symmetricReverseDeduplications = [int64]0
$asymmetricOrderedOccurrences = [int64]0

try {
    while ($reader.Read()) {
        if ($reader.NodeType -eq [System.Xml.XmlNodeType]::Element) {
            if ($reader.Name -eq 'rooms') {
                $inRooms = $true
            }
            elseif ($reader.Name -eq 'courses') {
                $inCourses = $true
            }
            elseif ($reader.Name -eq 'distributions') {
                $inDistributions = $true
            }
            elseif ($inRooms -and $reader.Name -eq 'room' -and $null -eq $rootRoomId) {
                $rootRoomId = $reader.GetAttribute('id')
                $rootRoomDepth = $reader.Depth
            }
            elseif (
                $null -ne $rootRoomId -and
                $reader.Name -eq 'travel' -and
                $reader.Depth -eq ($rootRoomDepth + 1)
            ) {
                $key = $rootRoomId + ',' + $reader.GetAttribute('room')
                $travel[$key] = [int]$reader.GetAttribute('value')
            }
            elseif ($inCourses -and $reader.Name -eq 'class' -and $null -eq $classId) {
                $classId = $reader.GetAttribute('id')
                $classDepth = $reader.Depth
                $classRoomRequired = $reader.GetAttribute('room') -ne 'false'
                $classRoomList = [System.Collections.Generic.List[string]]::new()
            }
            elseif (
                $null -ne $classId -and
                $reader.Name -eq 'room' -and
                $reader.Depth -eq ($classDepth + 1)
            ) {
                $classRoomList.Add($reader.GetAttribute('id'))
            }
            elseif (
                $inDistributions -and
                $reader.Name -eq 'distribution' -and
                $null -eq $distributionType
            ) {
                $distributionType = $reader.GetAttribute('type')
                $distributionRequired = $reader.GetAttribute('required') -eq 'true'
                $distributionDepth = $reader.Depth
                $distributionClasses = [System.Collections.Generic.List[string]]::new()
            }
            elseif (
                $null -ne $distributionType -and
                $reader.Name -eq 'class' -and
                $reader.Depth -eq ($distributionDepth + 1)
            ) {
                $distributionClasses.Add($reader.GetAttribute('id'))
            }
        }
        elseif ($reader.NodeType -eq [System.Xml.XmlNodeType]::EndElement) {
            if (
                $null -ne $rootRoomId -and
                $reader.Name -eq 'room' -and
                $reader.Depth -eq $rootRoomDepth
            ) {
                $rootRoomId = $null
                $rootRoomDepth = -1
            }
            elseif (
                $null -ne $classId -and
                $reader.Name -eq 'class' -and
                $reader.Depth -eq $classDepth
            ) {
                if (-not $classRoomRequired) {
                    $classRoomList.Add('__NONE__')
                }
                $classRooms[$classId] = $classRoomList.ToArray()
                $classId = $null
                $classDepth = -1
                $classRoomList = $null
            }
            elseif (
                $null -ne $distributionType -and
                $reader.Name -eq 'distribution' -and
                $reader.Depth -eq $distributionDepth
            ) {
                if ($distributionRequired -and $distributionType -eq 'SameAttendees') {
                    $seenDistributionClasses = @{}
                    $admittedClasses = [System.Collections.Generic.List[string]]::new()
                    foreach ($distributionClass in $distributionClasses) {
                        if (-not $seenDistributionClasses.ContainsKey($distributionClass)) {
                            $seenDistributionClasses[$distributionClass] = $true
                            $admittedClasses.Add($distributionClass)
                        }
                    }
                    for ($i = 0; $i -lt $admittedClasses.Count; $i++) {
                        for ($j = $i + 1; $j -lt $admittedClasses.Count; $j++) {
                            $firstClass = $admittedClasses[$i]
                            $secondClass = $admittedClasses[$j]
                            $rawPairOccurrences++
                            $orderedKey = $firstClass + ',' + $secondClass
                            if ($exactOrdered.ContainsKey($orderedKey)) {
                                continue
                            }
                            $exactOrdered[$orderedKey] = $true
                            $symmetric = $true
                            foreach ($firstRoom in $classRooms[$firstClass]) {
                                foreach ($secondRoom in $classRooms[$secondClass]) {
                                    if ($firstRoom -eq '__NONE__' -or $secondRoom -eq '__NONE__') {
                                        $forward = 0
                                        $reverse = 0
                                    }
                                    else {
                                        $forwardKey = $firstRoom + ',' + $secondRoom
                                        $reverseKey = $secondRoom + ',' + $firstRoom
                                        if ($travel.ContainsKey($forwardKey)) {
                                            $forward = [int]$travel[$forwardKey]
                                        }
                                        elseif ($travel.ContainsKey($reverseKey)) {
                                            $forward = [int]$travel[$reverseKey]
                                        }
                                        else {
                                            $forward = 0
                                        }
                                        if ($travel.ContainsKey($reverseKey)) {
                                            $reverse = [int]$travel[$reverseKey]
                                        }
                                        elseif ($travel.ContainsKey($forwardKey)) {
                                            $reverse = [int]$travel[$forwardKey]
                                        }
                                        else {
                                            $reverse = 0
                                        }
                                    }
                                    if ($forward -ne $reverse) {
                                        $symmetric = $false
                                        break
                                    }
                                }
                                if (-not $symmetric) {
                                    break
                                }
                            }
                            if ($symmetric) {
                                if ([int64]$firstClass -le [int64]$secondClass) {
                                    $safeKey = 'S:' + $firstClass + ',' + $secondClass
                                }
                                else {
                                    $safeKey = 'S:' + $secondClass + ',' + $firstClass
                                }
                            }
                            else {
                                $safeKey = 'O:' + $firstClass + ',' + $secondClass
                                $asymmetricOrderedOccurrences++
                            }
                            if ($safeRelations.ContainsKey($safeKey)) {
                                if ($symmetric) {
                                    $symmetricReverseDeduplications++
                                }
                                continue
                            }
                            $evaluations = (
                                [int64]$classRooms[$firstClass].Count *
                                [int64]$classRooms[$secondClass].Count
                            )
                            $safeRelations[$safeKey] = $evaluations
                            $safeEvaluations += $evaluations
                        }
                    }
                }
                $distributionType = $null
                $distributionRequired = $false
                $distributionClasses = $null
                $distributionDepth = -1
            }
            elseif ($reader.Name -eq 'rooms') {
                $inRooms = $false
            }
            elseif ($reader.Name -eq 'courses') {
                $inCourses = $false
            }
            elseif ($reader.Name -eq 'distributions') {
                $inDistributions = $false
            }
        }
    }
}
finally {
    $reader.Dispose()
}

$exactOrderedEvaluations = [int64]0
foreach ($orderedKey in $exactOrdered.Keys) {
    $parts = $orderedKey.Split(',')
    $exactOrderedEvaluations += (
        [int64]$classRooms[$parts[0]].Count *
        [int64]$classRooms[$parts[1]].Count
    )
}

$result = [ordered]@{
    schema = 'planora.itc2019.sameattendees-static-admission.v1'
    input_path = $resolvedInput
    input_sha256 = (Get-FileHash -LiteralPath $resolvedInput -Algorithm SHA256).Hash.ToLowerInvariant()
    algorithm = 'exact-ordered-dedup-plus-full-domain-travel-symmetry-proof'
    class_count = $classRooms.Count
    directed_travel_entries = $travel.Count
    raw_pair_occurrences = $rawPairOccurrences
    exact_ordered_pairs = $exactOrdered.Count
    exact_ordered_evaluations = $exactOrderedEvaluations
    safe_prepared_relations = $safeRelations.Count
    safe_prepared_evaluations = $safeEvaluations
    symmetric_reverse_deduplications = $symmetricReverseDeduplications
    asymmetric_ordered_occurrences = $asymmetricOrderedOccurrences
    reduction_from_exact_ordered = $exactOrderedEvaluations - $safeEvaluations
    configured_cap = 2500000
    headroom = 2500000 - $safeEvaluations
    admitted = $safeEvaluations -le 2500000
    model_built = $false
    solver_run = $false
}
$result | ConvertTo-Json -Depth 4 -Compress
