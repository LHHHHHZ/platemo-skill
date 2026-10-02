function test_adapter_runtime_runner(platemoRoot,outputRoot)
% 小预算真实验证：模型注入、权重降级、短预算，以及普通算法保存。
    assert(isfolder(outputRoot),'Create a fresh output directory first.');
    cd(platemoRoot);
    cfg = struct('algorithms',{{struct('class','SET_NSGAIII','params',[2,2])}}, ...
        'problems',{{struct('class','DTLZ2','M',2,'D',5)}}, ...
        'N',6,'maxFE',42,'runs',1,'metrics',{{'IGD','HV'}},'save_count',2, ...
        'experiment_root',outputRoot,'experiment_id','online_pass');
    path = fullfile(outputRoot,'runtime_config.json');
    writeConfig(path,cfg);
    run_platemo_batch(path);
    manifest = jsondecode(fileread(fullfile(outputRoot,cfg.experiment_id,'manifest.json')));
    diag = manifest.records.runtime_diagnostics;
    assert(strcmp(diag.status,'passed') && diag.prediction_successes > 0 && diag.injected_solutions > 0);
    assert(diag.ga_fallbacks == 0 && diag.models.actual_mode == 2 && diag.training_steps > 0);
    fprintf('RUNTIME_ONLINE_PASS predictions=%d injected=%d\n',diag.prediction_successes,diag.injected_solutions);
    % 当前 D=5/M=2 的 schema 没有预训练权重，TRAIN=1 不能静默变成 TRAIN=2。
    cfg.algorithms{1}.params = [1,2];
    cfg.experiment_id = 'missing_weights';
    writeConfig(path,cfg);
    assertFailure(path,outputRoot,cfg.experiment_id,'training_mode_mismatch');
    cfg.algorithms{1}.params = [2,20];
    cfg.experiment_id = 'short_budget';
    cfg.maxFE = 12;
    writeConfig(path,cfg);
    assertFailure(path,outputRoot,cfg.experiment_id,'surrogate_not_exercised');
    cfg.experiment_id = 'no_training';
    cfg.maxFE = 42;
    cfg.algorithms{1}.params = [2,1];
    writeConfig(path,cfg);
    assertFailure(path,outputRoot,cfg.experiment_id,'training_not_exercised');
    cfg.experiment_id = 'invalid_mode';
    cfg.algorithms{1}.params = [3,2];
    writeConfig(path,cfg);
    assertFailure(path,outputRoot,cfg.experiment_id,'dependency_preflight_failed');
    module = py.importlib.import_module('SetTransformer');
    assert(~logical(py.hasattr(module,'_platemo_runtime_monitor')),'Runtime wrapper must be removed after each run.');
    % MATLAB 转换等失败可能发生在 Python 返回成功之后，仍需核对算法日志。
    logPath = fullfile(outputRoot,'matlab_failure.log');
    diary(logPath);
    runtime = SetNSGAIIIRuntime({2,2},fileparts(which('run_platemo_batch')),logPath);
    runtime.ensurePreflight();
    module = py.importlib.import_module('SetTransformer');
    reset = py.getattr(module,'clear_model_cache');
    reset();
    fprintf('Warning: Set Transformer failed at generation 5: simulated MATLAB conversion failure\n');
    diag = runtime.report(false);
    assert(strcmp(diag.status,'failed') && diag.ga_fallbacks == 1);
    runtime.close();
    diary off;
    fprintf('RUNTIME_RUNNER_TEST_PASS online=1 fallback_rejected=1 short_budget_rejected=1 no_training_rejected=1 preflight_rejected=1 matlab_failure_rejected=1 restored=1\n');
end

function assertFailure(path,root,id,expectedCode)
    rejected = false;
    try
        run_platemo_batch(path);
    catch ME
        rejected = strcmp(ME.identifier,'PlatEMO:BatchFailed');
    end
    assert(rejected,'Invalid surrogate experiment must fail.');
    manifest = jsondecode(fileread(fullfile(root,id,'manifest.json')));
    assert(strcmp(manifest.status,'failed'));
    diag = manifest.records.runtime_diagnostics;
    issues = diag.issues;
    if iscell(issues), codes = cellfun(@(s)s.code,issues,'UniformOutput',false); else, codes = {issues.code}; end
    assert(ismember(expectedCode,codes),'Expected runtime issue was not archived.');
    assert(isfile(fullfile(root,id,'Data','a001_p001','run_1_diagnostics.json')));
    assert(isempty(dir(fullfile(root,id,'Data','a001_p001','*.mat'))),'Invalid run must not save a successful result.');
end

function writeConfig(path,cfg)
    fid = fopen(path,'w','n','UTF-8');
    assert(fid >= 0,'Cannot create test config.');
    guard = onCleanup(@()fclose(fid)); %#ok<NASGU>
    fprintf(fid,'%s',jsonencode(cfg));
end
